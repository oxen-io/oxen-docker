#!/usr/bin/env python3

import subprocess
import tempfile
import optparse
import sys
from concurrent.futures import ThreadPoolExecutor
import threading

parser = optparse.OptionParser()
parser.add_option("--no-cache", action="store_true",
                  help="Run `docker build` with the `--no-cache` option to ignore existing images")
parser.add_option("--parallel", "-j", type="int", default=1,
                  help="Run up to this many builds in parallel")
parser.add_option("--distro", type="string", default="",
                  help="Build only this distro; should be DISTRO-CODE or DISTRO-CODE/ARCH, "
                       "e.g. debian-sid/amd64")
parser.add_option('--no-push', action="store_true",
                  help="push built images to docker repository")

(options, args) = parser.parse_args()

registry_base = 'registry.oxen.rocks/lokinet-ci-'

distros = [*(('debian', x) for x in ('sid', 'stable', 'testing', 'bullseye', 'buster')),
           *(('ubuntu', x) for x in ('rolling', 'lts', 'impish', 'hirsute', 'focal', 'bionic'))]

if options.distro:
    d = options.distro.split('-')
    if len(d) != 2 or d[0] not in ('debian', 'ubuntu') or not d[1]:
        print(f"Bad --distro value '{options.distro}'", file=sys.stderr)
        sys.exit(1)
    distros = [(d[0], d[1].split('/')[0])]


manifests = {}  # "image:latest": ["image/amd64", "image/arm64v8", ...]
manifestlock = threading.Lock()

dep_jobs = {}  # image => [remaining_jobs, queue_dep_jobs_callbacks...]
cancel_jobs = False
jobs_lock = threading.Lock()


def arches(distro):
    if options.distro and '/' in options.distro:
        arch = options.distro.split('/')
        if arch[1] not in ('amd64', 'i386', 'arm64v8', 'arm32v7'):
            print(f"Bad --distro value '{options.distro}'", file=sys.stderr)
            sys.exit(1)
        return [arch[1]]

    a = ['amd64', 'arm64v8', 'arm32v7']
    if distro[0] == 'debian' or distro == ('ubuntu', 'bionic'):
        a.append('i386')  # i386 builds don't work on later ubuntu
    return a


hacks = {
    registry_base + 'ubuntu-bionic-builder': """g++-8 \
            && mkdir -p /usr/lib/x86_64-linux-gnu/pgm-5.2/include""",
}


failure = False

lineno = 0
linelock = threading.Lock()


def print_line(myline, value):
    linelock.acquire()
    global lineno
    if sys.__stdout__.isatty():
        jump = lineno - myline
        print(f"\033[{jump}A\r\033[K{value}\033[{jump}B\r", end='')
        sys.stdout.flush()
    else:
        print(value)
    linelock.release()


def run_or_report(*args, myline):
    try:
        subprocess.run(
            args, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf8')
    except subprocess.CalledProcessError as e:
        with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as log:
            log.write(f"Error running {' '.join(args)}: {e}\n\nOutput:\n\n".encode())
            log.write(e.output.encode())
            global failure
            failure = True
            print_line(myline, f"\033[31;1mError! See {log.name} for details")
            raise e


def build_tag(tag_base, arch, contents, *, manifest_now=False):
    if failure:
        raise ChildProcessError()

    linelock.acquire()
    global lineno
    myline = lineno
    lineno += 1
    print()
    linelock.release()

    with tempfile.NamedTemporaryFile(dir='.') as dockerfile:
        dockerfile.write(contents.encode())
        dockerfile.flush()

        tag = f'{tag_base}/{arch}'
        print_line(myline,     f"\033[33;1mRebuilding        \033[35;1m{tag}\033[0m")
        run_or_report('docker', 'build', '--pull', '-f', dockerfile.name, '-t', tag,
                      *(('--no-cache',) if options.no_cache else ()), '.', myline=myline)
        if options.no_push:
            print_line(myline, f"\033[33;1mSkip Push         \033[35;1m{tag}\033[0m")
        else:
            print_line(myline, f"\033[33;1mPushing           \033[35;1m{tag}\033[0m")
            run_or_report('docker', 'push', tag, myline=myline)

        print_line(myline,     f"\033[32;1mFinished build    \033[35;1m{tag}\033[0m")

        latest = tag_base + ':latest'
        global manifests
        with manifestlock:
            if latest in manifests:
                manifests[latest].append(tag)
            else:
                manifests[latest] = [tag]

        if manifest_now:
            push_manifest(tag_base)


def check_done_build(tag):
    """
    Check if we're done build all the arch builds for 'tag' and if so, push the manifest and then
    start dependent jobs (if any).
    """
    done, depjobs = False, []
    with jobs_lock:
        if tag not in dep_jobs:
            done = True
        else:
            deps = dep_jobs[tag]
            assert deps[0] > 0
            deps[0] -= 1
            if deps[0] == 0:
                done = True
                depjobs = deps[1:]

    if done:
        push_manifest(tag)

        if depjobs:
            for q in depjobs:
                q()


def distro_build_base(distro, arch, *, initial_debian_stable=False):
    skip_build = (distro, arch) == (('debian', 'stable'), 'amd64') and not initial_debian_stable

    tag = f'{registry_base}{distro[0]}-{distro[1]}-base'
    codename = 'latest' if distro == ('ubuntu', 'lts') else distro[1]
    if not skip_build:
        build_tag(tag, arch, f"""
FROM {arch}/{distro[0]}:{codename}
RUN /bin/bash -c 'echo "man-db man-db/auto-update boolean false" | debconf-set-selections'
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 -q autoremove -y \
        {hacks.get(tag, '')}
""", manifest_now=initial_debian_stable)

    if not initial_debian_stable:
        check_done_build(tag)


def distro_build_builder(distro, arch):
    """
    (distro)-(codename)-builder: Deb builder image used for building debs; we add the basic tools we
    use to build debs, not including things that should come from the dependencies in the
    debian/control file.
    """
    base = f'{registry_base}{distro[0]}-{distro[1]}-base'
    tag = f'{registry_base}{distro[0]}-{distro[1]}-builder'
    build_tag(tag, arch, f"""
FROM {base}/{arch}
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 --no-install-recommends -q install -y \
        ccache \
        devscripts \
        equivs \
        g++ \
        git \
        git-buildpackage \
        openssh-client \
        {hacks.get(tag, '')}
""")

    check_done_build(tag)


def distro_build(distro, arch):
    """
    (distro)-(codename): Basic image we use for most builds.  This takes the -builder and adds most
    dependencies found in our packages.
    """
    builder = f'{registry_base}{distro[0]}-{distro[1]}-builder'
    tag = f'{registry_base}{distro[0]}-{distro[1]}'
    build_tag(tag, arch, f"""
FROM {builder}/{arch}
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 --no-install-recommends -q install -y \
        automake \
        ccache \
        cmake \
        curl \
        eatmydata \
        g++ \
        gdb \
        git \
        libboost-program-options-dev \
        libboost-serialization-dev \
        libboost-thread-dev \
        libcurl4-openssl-dev \
        libevent-dev \
        libgtest-dev \
        libhidapi-dev \
        libjemalloc-dev \
        libminiupnpc-dev \
        libreadline-dev \
        libsodium-dev \
        libsqlite3-dev \
        libssl-dev \
        libsystemd-dev \
        libtool \
        libunbound-dev \
        libunwind8-dev \
        libusb-1.0.0-dev \
        libuv1-dev \
        libzmq3-dev \
        lsb-release \
        make \
        nettle-dev \
        ninja-build \
        openssh-client \
        patch \
        pkg-config \
        postgresql-client \
        pybind11-dev \
        python3-coloredlogs \
        python3-cryptography \
        python3-dev \
        python3-flask \
        python3-nacl \
        python3-openssl \
        python3-pil \
        python3-pip \
        python3-protobuf \
        python3-psycopg2 \
        python3-pybind11 \
        python3-pycryptodome \
        python3-pytest \
        python3-qrencode \
        python3-setuptools \
        python3-sqlalchemy \
        python3-sqlalchemy-utils \
        python3-tabulate \
        python3-uwsgidecorators \
        qttools5-dev \
        sqlite3 \
        {hacks.get(tag, '')}
""")

    check_done_build(tag)


def debian_clang_build():
    """For debian-sid/amd64 we also build an extra one with clang+llvm"""

    tag = f'{registry_base}debian-sid-clang'
    build_tag(tag, 'amd64', f"""
FROM {registry_base}debian-sid/amd64
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 --no-install-recommends -q install -y \
        clang \
        lld \
        libc++-dev \
        libc++abi-dev
""", manifest_now=True)


# Android and flutter builds on top of debian-stable-base and adds a ton of android crap; we
# schedule this job as soon as the debian-sid-base/amd64 build finishes, because they easily take
# the longest and are by far the biggest images.
def android_builds():
    build_tag(registry_base + 'android', 'amd64', f"""
FROM {registry_base}debian-stable-base
RUN /bin/bash -c 'sed -i "s/main/main contrib/g" /etc/apt/sources.list'
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 -q install --no-install-recommends -y \
        android-sdk \
        automake \
        ccache \
        cmake \
        curl \
        git \
        google-android-ndk-installer \
        libtool \
        make \
        openssh-client \
        patch \
        pkg-config \
        wget \
        xz-utils \
        zip \
    && git clone https://github.com/Shadowstyler/android-sdk-licenses.git /tmp/android-sdk-licenses \
    && cp -a /tmp/android-sdk-licenses/*-license /usr/lib/android-sdk/licenses \
    && rm -rf /tmp/android-sdk-licenses
""", manifest_now=True)
    build_tag(registry_base + 'flutter', 'amd64', f"""
FROM {registry_base}android
RUN cd /opt \
    && curl https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_2.10.3-stable.tar.xz \
        | tar xJv \
    && ln -s /opt/flutter/bin/flutter /usr/local/bin/ \
    && flutter upgrade && flutter precache
""", manifest_now=True)


# lint is a tiny build (on top of debian-stable-base) with just formatting checking tools
def lint_build():
    build_tag(registry_base + 'lint', 'amd64', f"""
FROM {registry_base}debian-stable-base
RUN apt-get -o=Dpkg::Use-Pty=0 -q install --no-install-recommends -y \
    clang-format-11 \
    eatmydata \
    git \
    jsonnet
""", manifest_now=True)


def nodejs_build():
    build_tag(registry_base + 'nodejs', 'amd64', """
FROM node:14.16.1
RUN /bin/bash -c 'echo "man-db man-db/auto-update boolean false" | debconf-set-selections'
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 -q install --no-install-recommends -y \
        ccache \
        cmake \
        eatmydata \
        g++ \
        gdb \
        git \
        make \
        ninja-build \
        openssh-client \
        patch \
        pkg-config \
        wine
""", manifest_now=True)


def debian_win32_cross():
    build_tag(f'{registry_base}debian-win32-cross', 'amd64', f"""
FROM {registry_base}debian-stable-base/amd64
RUN apt-get -o=Dpkg::Use-Pty=0 -q install --no-install-recommends -y \
        autoconf \
        automake \
        build-essential \
        ccache \
        cmake \
        eatmydata \
        file \
        g++-mingw-w64-x86-64 \
        git \
        gperf \
        libtool \
        make \
        ninja-build \
        nsis \
        openssh-client \
        patch \
        pkg-config \
        qttools5-dev \
        zip \
    && update-alternatives --set x86_64-w64-mingw32-gcc /usr/bin/x86_64-w64-mingw32-gcc-posix \
    && update-alternatives --set x86_64-w64-mingw32-g++ /usr/bin/x86_64-w64-mingw32-g++-posix
""", manifest_now=True)


def debian_cross_build():
    """ build debian cross compiler image """
    tag = f'{registry_base}debian-stable-cross'
    compilers = ' '.join(f'g++-{a} gcc-{a}' for a in (
        'aarch64-linux-gnu', 'arm-linux-gnueabihf', 'mips-linux-gnu', 'mips64-linux-gnuabi64',
        'mipsel-linux-gnu', 'powerpc64le-linux-gnu'))

    build_tag(tag, 'amd64', f"""
FROM {registry_base}debian-stable/amd64
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 -q install -y {compilers}
""", manifest_now=True)


def build_docs():
    """ documentation builder image """

    build_tag(f'{registry_base}docbuilder', 'amd64', f"""
FROM {registry_base}debian-stable/amd64
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 -q install -y doxygen mkdocs curl zip unzip tar

RUN git clone --recursive https://github.com/matusnovak/doxybook2 /usr/local/src/doxybook2 \
   && git clone https://github.com/microsoft/vcpkg /usr/local/src/vcpkg \
   && /usr/local/src/vcpkg/bootstrap-vcpkg.sh \
   && /usr/local/src/vcpkg/vcpkg install --triplet x64-linux $(cat /usr/local/src/doxybook2/vcpkg.txt) \
   && cmake -S /usr/local/src/doxybook2 -B /usr/local/src/doxybook2/build -DCMAKE_TOOLCHAIN_FILE=/usr/local/src/vcpkg/scripts/buildsystems/vcpkg.cmake \
   && make -C /usr/local/src/doxybook2/build install -j$(nproc) \
   && rm -rf /usr/local/src/doxybook2 /usr/local/src/vcpkg
""", manifest_now=True)


def push_manifest(image):
    if options.no_push:
        return

    if failure:
        raise ChildProcessError()

    latest = image + ':latest'
    with manifestlock:
        tags = list(manifests[latest])
    with linelock:
        global lineno
        myline = lineno
        lineno += 1
        print()

    subprocess.run(['docker', 'manifest', 'rm', latest], stderr=subprocess.DEVNULL, check=False)
    print_line(myline, f"\033[33;1mCreating manifest \033[35;1m{latest}\033[0m")
    run_or_report('docker', 'manifest', 'create', latest, *tags, myline=myline)
    print_line(myline, f"\033[33;1mPushing manifest  \033[35;1m{latest}\033[0m")
    run_or_report('docker', 'manifest', 'push', latest, myline=myline)
    print_line(myline, f"\033[32;1mFinished manifest \033[35;1m{latest}\033[0m")


# Start debian-stable-base/amd64 on its own, because other builds depend on it and we want to get
# those (especially android/flutter) fired off as soon as possible (because it's slow and huge).
if ('debian', 'stable') in distros:
    distro_build_base(['debian', 'stable'], 'amd64', initial_debian_stable=True)

executor = ThreadPoolExecutor(max_workers=max(options.parallel, 1))

if options.distro:
    jobs = []
else:
    jobs = [executor.submit(b) for b in (android_builds, lint_build, nodejs_build, debian_win32_cross)]

with jobs_lock:
    # We do some basic dependency handling here: we start off all the -base images right away, then
    # schedule -builder to follow once -base is done on *all* arches (and the manifest pushed), then
    # the unsuffixed once -builder is done on all arches with manifest pushed.
    #
    # Docker sucks balls, though, so if anything goes wrong you'll just get some useless error about
    # the manifest not existing (you also sometimes just get that randomly as a failure as well,
    # because docker).

    for d in distros:
        archlist = arches(d)
        def next_wave(build_func):
            dist = d
            arches = archlist
            def f():
                with jobs_lock:
                    for a in arches:
                        jobs.append(executor.submit(build_func, dist, a))
            return f
        def next_singleton(build_func):
            def f():
                with jobs_lock:
                    jobs.append(executor.submit(build_func))
            return f

        prefix = f"{registry_base}{d[0]}-{d[1]}"
        dep_jobs[prefix + "-base"] = [len(archlist), next_wave(distro_build_builder)]
        dep_jobs[prefix + "-builder"] = [len(archlist), next_wave(distro_build)]
        dep_jobs[prefix] = [len(archlist)]
        if d == ('debian', 'stable') and 'amd64' in archlist:
            dep_jobs[prefix].extend(next_singleton(f) for f in (debian_cross_build, build_docs))
        if d == ('debian', 'sid') and 'amd64' in archlist:
            dep_jobs[prefix].append(next_singleton(debian_clang_build))

        for a in archlist:
            jobs.append(executor.submit(distro_build_base, d, a))

while True:
    with jobs_lock:
        if not jobs:
            break
        j = jobs.pop(0)

    try:
        j.result()
    except (ChildProcessError, subprocess.CalledProcessError):
        with jobs_lock:
            failure = True
            dep_jobs.clear()
            for k in jobs:
                k.cancel()

if failure:
    print("Error(s) occured, aborting!", file=sys.stderr)
    sys.exit(1)


print("\n\n\033[32;1mAll done!\n")
