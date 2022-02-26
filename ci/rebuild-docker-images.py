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
        print("Bad --distro value '{}'".format(options.distro), file=sys.stderr)
        sys.exit(1)
    distros = [(d[0], d[1].split('/')[0])]


manifests = {}  # "image:latest": ["image/amd64", "image/arm64v8", ...]
manifestlock = threading.Lock()


def arches(distro):
    if options.distro and '/' in options.distro:
        arch = options.distro.split('/')
        if arch[1] not in ('amd64', 'i386', 'arm64v8', 'arm32v7'):
            print("Bad --distro value '{}'".format(options.distro), file=sys.stderr)
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
        print("\033[{jump}A\r\033[K{value}\033[{jump}B\r".format(jump=jump, value=value), end='')
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
            log.write("Error running {}: {}\n\nOutput:\n\n".format(' '.join(args), e).encode())
            log.write(e.output.encode())
            global failure
            failure = True
            print_line(myline, "\033[31;1mError! See {} for details".format(log.name))
            raise e


def build_tag(tag_base, arch, contents):
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

        tag = '{}/{}'.format(tag_base, arch)
        print_line(myline, "\033[33;1mRebuilding     \033[35;1m{}\033[0m".format(tag))
        run_or_report('docker', 'build', '--pull', '-f', dockerfile.name, '-t', tag,
                      *(('--no-cache',) if options.no_cache else ()), '.', myline=myline)
        if options.no_push:
            print_line(myline, "\033[33;1mSkip Push      \033[35;1m{}\033[0m".format(tag))
        else:
            print_line(myline, "\033[33;1mPushing        \033[35;1m{}\033[0m".format(tag))
            run_or_report('docker', 'push', tag, myline=myline)
        print_line(myline, "\033[32;1mFinished build \033[35;1m{}\033[0m".format(tag))

        latest = tag_base + ':latest'
        global manifests
        manifestlock.acquire()
        if latest in manifests:
            manifests[latest].append(tag)
        else:
            manifests[latest] = [tag]
        manifestlock.release()


def base_distro_build(distro, arch):
    tag = '{r}{distro[0]}-{distro[1]}-base'.format(r=registry_base, distro=distro)
    codename = 'latest' if distro == ('ubuntu', 'lts') else distro[1]
    build_tag(tag, arch, """
FROM {}/{}:{}
RUN /bin/bash -c 'echo "man-db man-db/auto-update boolean false" | debconf-set-selections'
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 -q autoremove -y \
        {hacks}
""".format(arch, distro[0], codename, hacks=hacks.get(tag, '')))


def distro_build(distro, arch):
    prefix = '{r}{distro[0]}-{distro[1]}'.format(r=registry_base, distro=distro)
    fmtargs = dict(arch=arch, distro=distro, prefix=prefix)

    # (distro)-(codename)-base: Base image from upstream: we sync the repos, but do nothing else.
    if (distro, arch) != (('debian', 'stable'), 'amd64'):  # debian-stable-base/amd64 already built
        base_distro_build(distro, arch)

    # (distro)-(codename)-builder: Deb builder image used for building debs; we add the basic tools
    # we use to build debs, not including things that should come from the dependencies in the
    # debian/control file.
    build_tag(prefix + '-builder', arch, """
FROM {prefix}-base/{arch}
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
        {hacks}
""".format(**fmtargs, hacks=hacks.get(prefix + '-builder', '')))

    # (distro)-(codename): Basic image we use for most builds.  This takes the -builder and adds
    # most dependencies found in our packages.
    build_tag(prefix, arch, """
FROM {prefix}-builder/{arch}
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
        {hacks}
""".format(**fmtargs, hacks=hacks.get(prefix, '')))

    # For debian-sid/amd64 we also build an extra one with clang+llvm
    if (distro, arch) == (('debian', 'sid'), 'amd64'):
        build_tag(prefix + '-clang', arch, """
FROM {prefix}/{arch}
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 --no-install-recommends -q install -y \
        clang \
        lld \
        libc++-dev \
        libc++abi-dev
""".format(**fmtargs, hacks=hacks.get(prefix, '')))

    # Debian stable amd64 add-on builds:
    if (distro, arch) == (('debian', 'stable'), 'amd64'):
        debian_cross_build()
        build_docs()


# Android and flutter builds on top of debian-stable-base and adds a ton of android crap; we
# schedule this job as soon as the debian-sid-base/amd64 build finishes, because they easily take
# the longest and are by far the biggest images.
def android_builds():
    build_tag(registry_base + 'android', 'amd64', """
FROM {r}debian-stable-base
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
""".format(r=registry_base))

    build_tag(registry_base + 'flutter', 'amd64', """
FROM {r}android
RUN cd /opt \
    && curl https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_2.2.2-stable.tar.xz \
        | tar xJv \
    && ln -s /opt/flutter/bin/flutter /usr/local/bin/ \
    && flutter precache
""".format(r=registry_base))


# lint is a tiny build (on top of debian-stable-base) with just formatting checking tools
def lint_build():
    build_tag(registry_base + 'lint', 'amd64', """
FROM {r}debian-stable-base
RUN apt-get -o=Dpkg::Use-Pty=0 -q install --no-install-recommends -y \
    clang-format-11 \
    eatmydata \
    git \
    jsonnet
""".format(r=registry_base))


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
""")


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
""")


def debian_cross_build(distro=['debian', 'stable'],
                       cross_targets=('aarch64-linux-gnu',
                                      'arm-linux-gnueabihf',
                                      'mips-linux-gnu',
                                      'mips64-linux-gnuabi64',
                                      'mipsel-linux-gnu',
                                      'powerpc64le-linux-gnu')):
    """ build debian cross compiler image """
    arch='amd64'
    prefix = f'{registry_base}{distro[0]}-{distro[1]}'
    build_tag(prefix + '-cross', arch, """
FROM {prefix}/{arch}
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 -q install -y {compilers}""".format(prefix=prefix, arch=arch, compilers=' '.join([f'g++-{arch} gcc-{arch}' for arch in cross_targets])))

def build_docs(distro=['debian', 'stable'],
               apt_packages=('doxygen', 'mkdocs', 'curl', 'zip', 'unzip', 'tar')):
    """ documentation builder image """
    arch='amd64'
    prefix = f'{registry_base}{distro[0]}-{distro[1]}'
    build_tag(f'{registry_base}docbuilder', arch, """
FROM {prefix}/{arch}
RUN apt-get -o=Dpkg::Use-Pty=0 -q update \
    && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y \
    && apt-get -o=Dpkg::Use-Pty=0 -q install -y {apt_packages}

RUN git clone --recursive https://github.com/matusnovak/doxybook2 /usr/local/src/doxybook2 \
   && git clone https://github.com/microsoft/vcpkg /usr/local/src/vcpkg \
   && /usr/local/src/vcpkg/bootstrap-vcpkg.sh \
   && /usr/local/src/vcpkg/vcpkg install --triplet x64-linux $(cat /usr/local/src/doxybook2/vcpkg.txt) \
   && cmake -S /usr/local/src/doxybook2 -B /usr/local/src/doxybook2/build -DCMAKE_TOOLCHAIN_FILE=/usr/local/src/vcpkg/scripts/buildsystems/vcpkg.cmake \
   && make -C /usr/local/src/doxybook2/build install -j$(nproc) \
   && rm -rf /usr/local/src/doxybook2 /usr/local/src/vcpkg
""".format(prefix=prefix, arch=arch, apt_packages=' '.join(apt_packages)))

# Start debian-stable-base/amd64 on its own, because other builds depend on it and we want to get
# those (especially android/flutter) fired off as soon as possible (because it's slow and huge).
if ('debian', 'stable') in distros:
    base_distro_build(['debian', 'stable'], 'amd64')

executor = ThreadPoolExecutor(max_workers=max(options.parallel, 1))

if options.distro:
    jobs = []
else:
    jobs = [executor.submit(b) for b in (android_builds, lint_build, nodejs_build, debian_win32_cross)]

for d in distros:
    for a in arches(d):
        jobs.append(executor.submit(distro_build, d, a))

while len(jobs):
    j = jobs.pop(0)
    try:
        j.result()
    except (ChildProcessError, subprocess.CalledProcessError):
        for k in jobs:
            k.cancel()

if failure:
    print("Error(s) occured, aborting!", file=sys.stderr)
    sys.exit(1)


print("\n\n\033[32;1mAll builds finished successfully; pushing manifests...\033[0m\n")


def push_manifest(latest, tags):
    if options.no_push:
        return

    if failure:
        raise ChildProcessError()

    linelock.acquire()
    global lineno
    myline = lineno
    lineno += 1
    print()
    linelock.release()

    subprocess.run(['docker', 'manifest', 'rm', latest], stderr=subprocess.DEVNULL, check=False)
    print_line(myline, "\033[33;1mCreating manifest \033[35;1m{}\033[0m".format(latest))
    run_or_report('docker', 'manifest', 'create', latest, *tags, myline=myline)
    print_line(myline, "\033[33;1mPushing manifest  \033[35;1m{}\033[0m".format(latest))
    run_or_report('docker', 'manifest', 'push', latest, myline=myline)
    print_line(myline, "\033[32;1mFinished manifest \033[35;1m{}\033[0m".format(latest))


for latest, tags in manifests.items():
    jobs.append(executor.submit(push_manifest, latest, tags))

while len(jobs):
    j = jobs.pop(0)
    try:
        j.result()
    except (ChildProcessError, subprocess.CalledProcessError):
        for k in jobs:
            k.cancel()


print("\n\n\033[32;1mAll done!\n")
