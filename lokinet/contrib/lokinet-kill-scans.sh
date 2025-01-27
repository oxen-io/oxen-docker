#!/bin/bash
#
# run every minute with cron
# If I understand correctly, this script is responsible for blocking IPs that are attempting to DDOS the server with SYN FLOOD type attacks.
# There are some issues with this script, it would be much better to implement it using fail2ban with an expiry time, ability to whitelist and notify
# I could be wrong but it could cause an issue if the SYN/ACK packets are coming from IPs masquerading as legit SNs as a way to impact the network?
# https://serverfault.com/questions/640873/how-to-ban-syn-flood-attacks-using-fail2ban
# This seems like a more elegant solution


for ip  in $( conntrack -p tcp -L | grep SYN_SENT | cut -d'=' -f 2 | cut -d' ' -f 1 | sort | uniq -c | awk '$1 > 1000 { print $2 ; }' ) ; do
        echo "banning $ip"
        iptables -A FORWARD -p TCP -j REJECT --reject-with tcp-reset -s $ip
done
