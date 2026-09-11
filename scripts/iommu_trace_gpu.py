# SPDX-FileCopyrightText: Samsung Electronics Co., Ltd
#
# SPDX-License-Identifier: BSD-3-Clause

"""
Trace the IOMMU map granularity while a GPU dma-buf is imported for a device
============================================================================

Runs the dma-buf probe in its peer-to-peer variant (``--bdf``) and dumps the
``iommu:map``/``iommu:unmap`` trace around it.

What this can and cannot see: NVIDIA's dma-buf exporter maps the buffer
through its own path, so the GPU window's 1 GiB attach is **not** visible in
the kernel's generic ``iommu:map`` tracepoint. What the trace does show is the
size of the kernel-mediated DMA mappings CUDA performs while the context is
set up -- on sid those are 2 MiB units with 2 MiB-aligned IOVA and physical
addresses, which is the kernel superpage leaf in action (Intel VT-d maps any
2 MiB-aligned, contiguous range as one 2 MiB page). The primary evidence for
the GPU buffer itself stays the probe's ``GET_MAP``: one 1 GiB segment at the
BAR2 base versus 16384 x 64 KiB in the no-IOMMU misc path.

Use ``tasks/trace_iommu_gpu.yaml`` to run it; the full trace is written to
``artifacts/iommu-trace-gpu/trace.txt`` and only the superpage-sized events
(``size >= 65536``) are printed to the console.
"""

import errno
import logging as log
import re
from argparse import ArgumentParser
from pathlib import Path

from cijoe.core.resources import get_resources

from dmabuf_import_probe import (
    PROBE_REMOTE_BIN,
    PROBE_REMOTE_SRC,
    PROBE_RESOURCE,
    compile_probe,
)

TRACE_DIR = "/sys/kernel/debug/tracing"
SIZE_LINE = re.compile(r"\bsize=(\d+)")


def add_args(parser: ArgumentParser):
    parser.add_argument(
        "--bdf",
        type=str,
        required=True,
        help="NVMe PCI address to import on behalf of, e.g. 0000:4d:00.0",
    )
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


def artifacts_path(args):
    path = Path(args.output) / "artifacts" / "iommu-trace-gpu"
    path.mkdir(parents=True, exist_ok=True)
    return path


def superpage_lines(trace):
    """Keep only map/unmap lines whose size field is at least 64 KiB."""
    kept = []
    for line in trace.splitlines():
        if ": map:" not in line and ": unmap:" not in line:
            continue
        match = SIZE_LINE.search(line)
        if match and int(match.group(1)) >= 65536:
            kept.append(line)
    return "\n".join(kept)


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

    # Best-effort, the way iommu_trace_recon.sh does it. The setup below is
    # what decides whether tracing is usable.
    cijoe.run(f"mountpoint -q {TRACE_DIR} || mount -t tracefs nodev {TRACE_DIR}")

    for cmd in [
        f"echo 0 > {TRACE_DIR}/events/enable",
        f"echo 0 > {TRACE_DIR}/tracing_on",
        f"echo 8192 > {TRACE_DIR}/buffer_size_kb",
        f"echo 0 > {TRACE_DIR}/trace",
        f"echo 'iommu:map' > {TRACE_DIR}/set_event",
        f"echo 'iommu:unmap' >> {TRACE_DIR}/set_event",
        f"echo 1 > {TRACE_DIR}/tracing_on",
    ]:
        err, state = cijoe.run(cmd)
        if err:
            # An unusable tracefs still lets the probe run and returns an empty
            # trace, which reads exactly like "no mappings happened".
            log.error(f"trace setup failed ({cmd}): {state.output()}")
            return err

    run_cmd = (
        f"{PROBE_REMOTE_BIN} --size_mib {args.size_mib} "
        f"--gpu_id {args.gpu_id} --bdf {args.bdf}"
    )
    probe_err, state = cijoe.run(run_cmd)
    probe_out = state.output()

    cijoe.run(f"echo 0 > {TRACE_DIR}/tracing_on")
    trace_err, state = cijoe.run(f"cat {TRACE_DIR}/trace")
    trace = state.output()

    path = artifacts_path(args)
    (path / "probe.out").write_text(probe_out)
    (path / "trace.txt").write_text(trace)

    print("== probe ==")
    print(probe_out)
    print("== trace (superpage-sized) ==")
    print(superpage_lines(trace))

    if probe_err:
        log.error(f"Probe failed with err({probe_err})")
        return probe_err

    if trace_err:
        log.error(f"failed reading trace: err({trace_err})")
        return trace_err

    return 0
