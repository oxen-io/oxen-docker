FROM registry.oxen.rocks/lokinet-base:latest

# set up configs for lokinet
COPY contrib/lokinet-exit.ini /var/lib/lokinet/conf.d/exit.ini

# set up system configs
COPY contrib/lokinet-exit-sysctl.conf /etc/sysctl.d/00-lokinet-exit.conf
COPY --chmod=700 contrib/lokinet-exit-rc.local.sh /etc/rc.local

# setup cron jobs
COPY --chmod=700 contrib/lokinet-kill-scans.sh /usr/local/sbin/lokinet-kill-scans.sh
COPY --chmod=700 contrib/lokinet-update-exit-address.sh /usr/local/sbin/lokinet-update-exit-address.sh

COPY --chmod=644 contrib/lokinet-exit.crontab /etc/cron.d/lokinet-exit

