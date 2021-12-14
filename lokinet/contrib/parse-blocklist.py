#!/usr/bin/python3
import itertools
import netaddr
import sys
from iblocklist2ipset.networks import convert_to_ipnetworks
from iblocklist2ipset.ipset import generate_ipset

def extract_networks(files):
    networks = itertools.chain.from_iterable(
        fetch_networks(f) for f in files
    )
    for network in netaddr.cidr_merge(networks):
        yield network

def fetch_networks(f):
    for item in f:
        for network in convert_to_ipnetworks(item):
            yield network

if len(sys.argv) == 1:
    for net in extract_networks([sys.stdin]):
        print(net)
