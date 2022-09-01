#!/bin/bash

# build ci docker images
cd ci && ./rebuild-docker-images.py -j ${PARALLEL:-$(nproc)} && cd -

# build lokinet docker images
make -C lokinet
