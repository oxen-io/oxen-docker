FROM registry.oxen.rocks/lokinet-base:latest

RUN /bin/bash -c 'apt-get -o=Dpkg::Use-Pty=0 -q update && apt-get -o=Dpkg::Use-Pty=0 -q dist-upgrade -y && apt-get -o=Dpkg::Use-Pty=0 -q install -y --no-install-recommends nginx'

# set up configs for lokinet nginx
COPY contrib/lokinet-nginx.ini /var/lib/lokinet/conf.d/nginx.ini
