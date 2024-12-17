FROM registry.oxen.rocks/lokinet-base:latest

RUN DEBIAN_FRONTEND=noninteractive \
    && apt-get update -y \
    && apt-get dist-upgrade -y \
    && apt-get install -y --no-install-recommends nginx

# set up configs for lokinet nginx
COPY contrib/lokinet-nginx.ini /var/lib/lokinet/conf.d/nginx.ini
