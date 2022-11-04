FROM registry.oxen.rocks/lokinet-base:latest

RUN DEBIAN_FRONTEND=noninteractive \
    && apt update -y \
    && apt apt full-upgrade -y \
    && apt install -y --no-install-recommends nginx

# set up configs for lokinet nginx
COPY contrib/lokinet-nginx.ini /var/lib/lokinet/conf.d/nginx.ini
