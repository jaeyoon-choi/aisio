# SPDX-FileCopyrightText: Samsung Electronics Co., Ltd
#
# SPDX-License-Identifier: BSD-3-Clause

"""
Dump the IOMMU mapping granularity of a CUDA dma-buf
====================================================

The probe allocates one large CUDA device-memory buffer, exports it as a
dma-buf, imports it through uPCIe's /dev/dmabuf_import, and prints the
``(dma_addr, dma_len)`` tuples that ``DMABUF_IMPORT_GET_MAP`` returns. Those
tuples are the export-side view, not the IOMMU mapping unit: the benchmark
maps the GPU heap through ``iommu_map_pa_add`` at 2 MiB
(``DMAMEM_CUDA_REGISTRY_GRANULARITY``), while GET_MAP shows 64 KiB export
pages on a misc import or NVIDIA's private map path merged into one segment
on a real-device (``--bdf``) import.

It also prints the CUDA allocation granularity (the coarse grain of what could
be one mapping) and DMABUF_IMPORT_DESCRIBE (where the buffer ended up: device
memory vs migrated to system memory).

The build needs the DMABUF_IMPORT UAPI, installed by
``tasks/setup_upcie_modules.yaml``, and CUDA. Compilation is attempted with
nvcc first, then a plain gcc link against libcuda.

Example:

  cijoe --monitor \\
      -c configs/transport.toml \\
      tasks/probe_dmabuf_import.yaml

Pass ``--bdf 0000:41:00.0`` to also import on behalf of an NVMe device, which
is the peer-to-peer path the addresses are actually programmed into. The
default (no bdf) performs the same misc-device enumeration the upcie-cuda
backend does; its actual 2 MiB IOMMU mapping is not exercised here.
"""

import errno
import logging as log
from argparse import ArgumentParser
from pathlib import Path

from cijoe.core.resources import get_resources

PROBE_RESOURCE = "dmabuf_import_probe"
PROBE_REMOTE_SRC = "/tmp/aisio-dmabuf-import-probe.c"
PROBE_REMOTE_BIN = "/tmp/aisio-dmabuf-import-probe"


def add_args(parser: ArgumentParser):
    parser.add_argument(
        "--size_mib",
        type=int,
        default=1024,
        help="CUDA buffer size in MiB to probe (default: 1024)",
    )
    parser.add_argument(
        "--gpu_id",
        type=int,
        default=0,
        help="CUDA device ordinal to allocate from (default: 0)",
    )
    parser.add_argument(
        "--bdf",
        type=str,
        default=None,
        help="NVMe PCI address to import on behalf of, e.g. 0000:41:00.0",
    )


def artifacts_path(args):
    path = Path(args.output) / "artifacts" / "dmabuf-import-probe"
    path.mkdir(parents=True, exist_ok=True)
    return path


def compile_probe(cijoe):
    """Compile the probe, trying nvcc then a plain gcc + libcuda link."""
    compile_cmds = [
        f"nvcc -o {PROBE_REMOTE_BIN} {PROBE_REMOTE_SRC} -lcuda",
        (
            f"gcc -O2 -o {PROBE_REMOTE_BIN} {PROBE_REMOTE_SRC} "
            "-I/usr/local/cuda/include -L/usr/local/cuda/lib64 -lcuda"
        ),
    ]

    for cmd in compile_cmds:
        err, state = cijoe.run(cmd)
        if not err:
            return 0
        log.info(f"compile failed ({cmd}):\n{state.output()}")

    return errno.ECOMM


def main(args, cijoe):
    probe = get_resources().get("auxiliary", {}).get(PROBE_RESOURCE, {})
    if not probe:
        log.error("Failed retrieving the probe source from auxiliary files")
        return errno.ENOENT

    if not cijoe.put(probe.path, PROBE_REMOTE_SRC):
        log.error("Failed transferring probe source to the target")
        return errno.EIO

    err = compile_probe(cijoe)
    if err:
        log.error("Failed compiling the probe on the target")
        return err

    run_cmd = f"{PROBE_REMOTE_BIN} --size_mib {args.size_mib} --gpu_id {args.gpu_id}"
    if args.bdf:
        run_cmd += f" --bdf {args.bdf}"

    err, state = cijoe.run(run_cmd)
    output = state.output()

    (artifacts_path(args) / "probe.out").write_text(output)
    print(output)

    if err:
        log.error(f"Probe failed with err({err})")
        return err

    return 0
