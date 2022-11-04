FROM registry.oxen.rocks/lokinet-exit:latest

RUN ln -s /var/lib/lokinet/conf.d/custom.ini /data/custom.ini
