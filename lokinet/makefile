
REG=registry.oxen.rocks

BUILD_IMAGE=./contrib/build-docker-images.sh

lokinet-nginx: lokinet-base test-env
	$(BUILD_IMAGE) $(REG) $@.dockerfile
lokinet-exit: lokinet-base test-env
	$(BUILD_IMAGE) $(REG) $@.dockerfile
lokinet-exit-custom: lokinet-exit test-env
	$(BUILD_IMAGE) $(REG) $@.dockerfile
lokinet-base: test-env
	$(BUILD_IMAGE) $(REG) $@.dockerfile

test-env:
	test x$(REG) != x

all: lokinet-authed-exit

