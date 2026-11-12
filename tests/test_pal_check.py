#!/usr/bin/env python3
# SPDX-FileCopyrightText: Samsung Electronics Co., Ltd
#
# SPDX-License-Identifier: BSD-3-Clause
"""
pal_check's xnvmeperf part against a stand-in host: it passes reads that all
complete, and fails a run that exits with an error, prints no result, fails a
read or leaves a DMAR fault. It runs xnvmeperf only with iommu_map_pa
unloaded and dmabuf_import loaded, and puts iommu_map_pa and the hugepage
count back whatever the run did.

    python3 tests/test_pal_check.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import pal_check  # noqa: E402

PCI_ADDR = "0000:4e:00.0"


def result(failed=0, iops="812345.12"):
    return (
        " Device                  CPUs          IOPS      MiB/s   Failed\n"
        f" {PCI_ADDR}               0  {iops:>12} {'3173.22':>10} {failed:>8}\n"
        "--------------------------------------------------------------------\n"
        f" {'Total:':<29} {iops:>12} {'3173.22':>10} {failed:>8}\n"
    )


class State:
    def __init__(self, text):
        self.text = text

    def output(self):
        return self.text


class Host:
    """The module and hugepage state pal_check reads, and what xnvmeperf does"""

    def __init__(
        self,
        out=None,
        err=0,
        map_pa=True,
        rmmod_err=0,
        dmabuf_import=True,
        nr=0,
        free=0,
        new_faults=0,
    ):
        self.out = result() if out is None else out
        self.err, self.map_pa, self.rmmod_err = err, map_pa, rmmod_err
        self.dmabuf_import, self.nr, self.free = dmabuf_import, nr, free
        self.new_faults, self.faults = new_faults, 3
        self.ran, self.map_pa_at_run = False, None

    def run(self, command):
        if command == "test -e /dev/dmabuf_import":
            return (0 if self.dmabuf_import else 1), State("")
        if command.startswith("test ! -d /sys/module/iommu_map_pa"):
            return 0, State("loaded\n" if self.map_pa else "")
        if command == "rmmod iommu_map_pa":
            if not self.rmmod_err:
                self.map_pa = False
            return self.rmmod_err, State("")
        if command == "modprobe iommu_map_pa":
            self.map_pa = True
            return 0, State("")
        if command == "cat /proc/sys/vm/nr_hugepages":
            return 0, State(f"{self.nr}\n")
        if command.startswith("awk '/^HugePages_Free:/"):
            return 0, State(f"{self.free}\n")
        if command.startswith("echo ") and command.endswith(
            "/proc/sys/vm/nr_hugepages"
        ):
            n = int(command.split()[1])
            self.free += n - self.nr
            self.nr = n
            return 0, State("")
        if command.startswith("dmesg"):
            return 0, State(f"{self.faults}\n")
        if command.startswith("XNVME_UPCIE_VFIO_MODE=iommufd xnvmeperf run"):
            assert command.endswith(f" {PCI_ADDR}")
            self.ran, self.map_pa_at_run = True, self.map_pa
            self.free_at_run = self.free
            self.faults += self.new_faults
            return self.err, State(self.out)
        raise AssertionError(f"unexpected command: {command}")


def check(name, host, vtd, want):
    loaded, nr = host.map_pa, host.nr
    failures = pal_check.xnvmeperf_reads(host, PCI_ADDR, vtd)
    assert failures == want, f"{name}: {failures} != {want}"
    if host.ran:
        assert host.map_pa_at_run is False, f"{name}: ran with iommu_map_pa loaded"
        assert host.free_at_run >= pal_check.HUGEPAGES, f"{name}: too few hugepages"
    assert host.map_pa == loaded, f"{name}: iommu_map_pa not put back"
    assert host.nr == nr, f"{name}: nr_hugepages not put back"
    print(f"ok: {name}")


def main():
    check("pass", Host(), True, [])
    check("pass with hugepages free", Host(nr=512, free=512), True, [])
    check("pass with no iommu_map_pa", Host(map_pa=False), True, [])
    check("not VT-d", Host(new_faults=2), False, [])
    check(
        "exit error",
        Host(err=234, out="FAILED: xnvme_dev_open()"),
        True,
        ["xnvmeperf: exited with 234"],
    )
    check("no result", Host(out="nothing"), True, ["xnvmeperf: printed no result"])
    check(
        "failed reads",
        Host(out=result(failed=7)),
        True,
        ["xnvmeperf: 7 reads failed"],
    )
    check(
        "no reads",
        Host(out=result(iops="0.00")),
        True,
        ["xnvmeperf: completed no read"],
    )
    check(
        "DMAR fault",
        Host(new_faults=1),
        True,
        ["xnvmeperf: the controller's DMA left DMAR faults"],
    )
    host = Host(dmabuf_import=False)
    check("no dmabuf_import", host, True, ["xnvmeperf: dmabuf_import is not loaded"])
    assert not host.ran
    host = Host(rmmod_err=1)
    check(
        "iommu_map_pa held",
        host,
        True,
        ["xnvmeperf: iommu_map_pa is in use and cannot be unloaded"],
    )
    assert not host.ran


if __name__ == "__main__":
    main()
