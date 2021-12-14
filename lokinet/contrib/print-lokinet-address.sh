#!/bin/bash
echo $(dig @127.3.2.1 +short -t cname localhost.loki | cut -d'.' -f1).loki
