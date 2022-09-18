#!/bin/bash

# the registry server to use
registry=$1

test "x$registry" != "x" || exit 1

for file in ${@:2} ; do
    name="$(echo $file | cut -d'.' -f1)"
    docker build -f $file -t $registry/$name:latest  .
    docker push $registry/$name:latest
done
