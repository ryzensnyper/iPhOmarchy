# SPDX-License-Identifier: GPL-2.0-only OR MIT
# Out-of-tree module for the G10P probe.  Built against the t8015 kernel tree.

ifneq ($(KERNELRELEASE),)

apple-t8015-gfx-iop-y := gfx_iop_t8015.o
obj-m += apple-t8015-gfx-iop.o

else

KDIR ?= /home/doug/orchard-d21
PWD := $(shell pwd)

.PHONY: modules clean
modules:
	$(MAKE) -C $(KDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- M=$(PWD) modules

# syntax-only check of the driver against the running kernel headers
# (does not require a full kernel build tree)
check:
	$(CC) -fsyntax-only -Wall -Wextra -I. gfx_iop_t8015.c

clean:
	$(MAKE) -C $(KDIR) ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- M=$(PWD) clean

endif
