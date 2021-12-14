#!/bin/bash
#
# run every minute with cron
#

for ip  in $( conntrack -p tcp -L | grep SYN_SENT | cut -d'=' -f 2 | cut -d' ' -f 1 | sort | uniq -c | awk '$1 > 1000 { print $2 ; }' ) ; do
        echo "banning $ip"
        iptables -A FORWARD -p TCP -j REJECT --reject-with tcp-reset -s $ip
done
