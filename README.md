# oxen-docker

All the docker related stuff for oxen-io repo namespace.

* [Lokinet docker images](lokinet)
* [Drone CI docker images](ci)


install deps:

    $ sudo apt install qemu-system qemu-user-binfmt docker.io

to rebuild all docker images:

    $ docker login registry.oxen.rocks
    $ ./rebuild-all.sh
