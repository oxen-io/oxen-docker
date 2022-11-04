#use argument instead of lsb-release
ARG DEBIAN_RELEASE=bullseye 

FROM debian:${DEBIAN_RELEASE}-slim AS lokinet-base
ENV container docker

ENV RELEASE=${DEBIAN_RELEASE:-bullseye}
#Add oxen public key 
ADD --chmod=644 --chown=_apt https://deb.oxen.io/pub.gpg /etc/apt/trusted.gpg.d/lokinet.gpg

# set up packages
# not sure if wget, lsb-release and curl are needed (maybe they can be removed to make a smaller image?)
RUN DEBIAN_FRONTEND=noninteractive \
    && echo "deb https://deb.oxen.io ${RELEASE} main" > /etc/apt/sources.list.d/lokinet.list \     
    && echo "man-db man-db/auto-update boolean false" | debconf-set-selections \
    && apt update -y \
    && apt full-upgrade -y \
    && apt install -y --no-install-recommends ca-certificates iptables dnsutils systemd systemd-sysv cron conntrack iproute2 python3-pip \
    && apt update -y \    
    && apt install -y --no-install-recommends lokinet \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/lib/lokinet/conf.d \
    && mkdir /data && chown _lokinet:_loki /data


# print lokinet util
COPY --chmod=700 contrib/print-lokinet-address.sh /usr/local/bin/print-lokinet-address.sh

# dns
COPY --chmod=644 contrib/lokinet.resolveconf.txt /etc/resolv.conf

STOPSIGNAL SIGRTMIN+3
ENTRYPOINT ["/sbin/init", "verbose", "systemd.unified_cgroup_hierarchy=0", "systemd.legacy_systemd_cgroup_controller=0"]
