FROM registry.oxen.rocks/lokinet-exit:latest

RUN /bin/bash -c 'ln -s /var/lib/lokinet/conf.d/custom.ini /data/custom.ini'
