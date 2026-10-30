#!/bin/sh
# Dev PC run of the guest_memfd export PoC, as the user after
# "sudo bind-nvme-vfio.sh jaeyoon". C2 cannot pass on this PC (the root
# complex rejects P2P reads), so it is reported but not judged here.
set -x
cd /data/gmem-poc
SLBA=2097152
date
uname -a
nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
./bin/pal_nvme --gmem --slba $SLBA --xfer 65536
./bin/pal_nvme --gmem --slba $SLBA --xfer 4096 --no-negative
./bin/pal_nvme --gmem --slba $SLBA --no-negative --map-loop 100
./bin/pal_nvme --map-pa 0000:02:00.0 --slba $SLBA --no-negative --map-loop 100
./bin/pal_nvme --gmem --slba $SLBA --no-negative --lifecycle close
./bin/pal_nvme --gmem --slba $SLBA --no-negative --lifecycle free
dmesg | grep -iE 'dmar|iommufd|guest_memfd|gpu_gmem|nvrm' | tail -40
