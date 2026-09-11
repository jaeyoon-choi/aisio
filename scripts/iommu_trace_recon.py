# SPDX-FileCopyrightText: Samsung Electronics Co., Ltd
#
# SPDX-License-Identifier: BSD-3-Clause

"""
Recon the IOMMU tracepoint surface on the target
================================================

Pushes and runs a shell script that inventories the ftrace tracepoints the
IOMMU drivers expose (the ``iommu`` and ``intel_iommu`` systems), their field
formats, the IOMMU groups, and the current NVMe/NVIDIA driver binding. The
fields tell us whether a follow-up can read the actual mapping granularity --
and, for Intel, the page-table walk decisions -- from the trace instead of the
unavailable debugfs page-table dump.
"""

import errno
import logging as log
from argparse import ArgumentParser
from pathlib import Path

from cijoe.core.resources import get_resources

SCRIPT_RESOURCE = "iommu_trace_recon"
SCRIPT_REMOTE = "/tmp/aisio-iommu-trace-recon.sh"


def add_args(parser: ArgumentParser):
    pass


def main(args, cijoe):
    script = get_resources().get("auxiliary", {}).get(SCRIPT_RESOURCE, {})
    if not script:
        log.error("Failed retrieving the recon script from auxiliary files")
        return errno.ENOENT

    if not cijoe.put(script.path, SCRIPT_REMOTE):
        log.error("Failed transferring recon script to the target")
        return errno.EIO

    err, state = cijoe.run(f"bash {SCRIPT_REMOTE}")
    output = state.output()

    path = Path(args.output) / "artifacts" / "iommu-trace-recon"
    path.mkdir(parents=True, exist_ok=True)
    (path / "recon.out").write_text(output)

    print(output)
    return err
