# SPDX-License-Identifier: GPL-2.0-only
KDIR ?= /lib/modules/$(shell uname -r)/build
NVSYMVERS ?= /data/nvidia-580-gmem/Module.symvers

obj-m := gpu_gmem_provider.o

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) KBUILD_EXTRA_SYMBOLS=$(NVSYMVERS) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
