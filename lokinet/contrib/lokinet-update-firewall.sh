#!/bin/bash

# There's definitely a better way to do this.

# get lokinet's address
if_name=lokitun0
if_range=$(ip addr show $if_name | grep inet\  | sed 's/inet //' | cut -d' ' -f5)

# drop blacklisted ranges
for range in $(wget --quiet https://raw.githubusercontent.com/Naunter/BT_BlockLists/master/bt_blocklists.gz -O - | zcat | parse-blocklist.py ) ; do
    iptables -A FORWARD -j REJECT -d $range -s $if_range &> /dev/null || true;
done
