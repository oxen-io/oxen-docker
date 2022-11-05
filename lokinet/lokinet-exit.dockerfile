FROM registry.oxen.rocks/lokinet-base:latest

# set up configs for lokinet
COPY contrib/lokinet-exit.ini /var/lib/lokinet/conf.d/exit.ini

# set up system configs
COPY contrib/lokinet-exit-sysctl.conf /etc/sysctl.d/00-lokinet-exit.conf
COPY --chmod=700 contrib/lokinet-exit-rc.local.sh /etc/rc.local

<<<<<<< HEAD
COPY --chmod=755 contrib/print-lokinet-address.sh /usr/local/bin/print-lokinet-address.sh

=======
>>>>>>> b13525e (More tweaks)
# setup cron jobs
COPY --chmod=700 contrib/lokinet-kill-scans.sh /usr/local/sbin/lokinet-kill-scans.sh
COPY --chmod=700 contrib/lokinet-update-exit-address.sh /usr/local/sbin/lokinet-update-exit-address.sh

COPY --chmod=644 contrib/lokinet-exit.crontab /etc/cron.d/lokinet-exit

