#!/bin/bash

# wait for lokinet
# to do what? How can we tell if lokinet has done what it needs to do?
sleep 10

# flush iptables
iptables -t nat --flush

# ip6tables -t nat --flush

# find default route's interface name
exit_if=$(ip route | grep ^default | cut -d' ' -f5)

# get lokinet's address
if_name=lokitun0
if_range=$(ip addr show $if_name | grep inet\  | sed 's/inet //' | cut -d' ' -f5)

# add ipv4 forward rule
iptables -t nat -A POSTROUTING -s $if_range -o $exit_if -j MASQUERADE


#I'm not sure what the loop below is supposed to do. It only runs once on port 25?
# drop outbound ports
for port in 25 ; do
        iptables -A FORWARD -p tcp --dport $port -j REJECT --reject-with tcp-reset -s $if_range
done

# set nameserver
echo 'nameserver 127.3.2.1' > /etc/resolv.conf
