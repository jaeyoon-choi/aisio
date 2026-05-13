"""
Collect uPCIe IOMMU overhead benchmark results
==============================================

Runs xnvmeperf and fio for one driver in the current boot configuration.
"""

import errno
import json
import logging as log
import re
import shlex
import time
from argparse import ArgumentParser
from pathlib import Path

from iommu_common import dmesg_indicates_iommu_enabled
from xnvmeperf import xnvmeperf_cmd

FIO_PERCENTILE_LIST = "99.9:99.99:99.999"
TAIL_LATENCIES = {
    "p99_9": "99.900000",
    "p99_99": "99.990000",
    "p99_999": "99.999000",
}
RW_TO_OP = {
    "read": "read",
    "randread": "read",
    "write": "write",
    "randwrite": "write",
}


def add_args(parser: ArgumentParser):
    parser.add_argument(
        "--driver", choices=["uio_pci_generic", "vfio-pci"], required=True
    )
    parser.add_argument("--label", choices=["uio", "vfio"], required=True)


def q(value):
    return shlex.quote(str(value))


def conf(cijoe, key, default=None):
    return cijoe.getconf(f"iommu_overhead.{key}", default)


def cpu_to_cpumask(cpu):
    return hex(1 << int(cpu))


def expected_iommu_enabled(driver):
    return driver == "vfio-pci"


def check_iommu_state(args, cijoe):
    cmd = "cat /proc/cmdline; echo; dmesg | grep -i -E 'DMAR|IOMMU|AMD-Vi' || true"
    err, state = cijoe.run(cmd)
    if err:
        log.error(f"Failed reading IOMMU state: {state}")
        return err

    enabled = dmesg_indicates_iommu_enabled(state.output())
    expected = expected_iommu_enabled(args.driver)
    if enabled != expected:
        mode = "enabled" if expected else "disabled"
        log.error(f"{args.driver} requires IOMMU {mode}; refusing to overwrite results")
        return errno.EINVAL

    return 0


def workload_cases(cijoe):
    for workload in conf(cijoe, "workloads", []):
        rw = workload["rw"]
        iosize = int(workload["iosize"])
        for iodepth in workload["iodepths"]:
            yield rw, iosize, int(iodepth)


def results_path(args):
    path = Path(args.output) / "artifacts" / "iommu-overhead" / args.label
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_command(cijoe, cmd):
    err, state = cijoe.run(cmd)
    if err:
        log.error(f"Failed command: {state}")
    return err, state.output()


def bind_driver(cijoe, driver, pci_addr, mountpoint, hugepages):
    commands = [
        f"modprobe {q(driver)}",
        f"umount {q(mountpoint)} || true",
        f"sysctl -w vm.nr_hugepages={q(hugepages)}",
        "mkdir -p /dev/hugepages",
        "mountpoint -q /dev/hugepages || mount -t hugetlbfs nodev /dev/hugepages",
        f"devbind --device {q(pci_addr)} --bind {q(driver)}",
    ]
    return run_command(cijoe, "\n".join(commands))[0]


def reset_driver(cijoe, pci_addr):
    err, _ = run_command(cijoe, f"devbind --device {q(pci_addr)} --bind nvme || true")
    return err


def build_xnvmeperf_cmd(cijoe, pci_addr, rw, iosize, iodepth):
    return xnvmeperf_cmd(
        "xnvmeperf",
        {
            "cpumask": cpu_to_cpumask(0),
            "qdepth": iodepth,
            "iosize": iosize,
            "runtime": int(conf(cijoe, "runtime", 10)),
            "iopattern": rw,
            "backend": "upcie",
            "devices": [pci_addr],
        },
    )


def fio_cmd(cijoe, pci_addr, rw, iosize, iodepth):
    runtime = int(conf(cijoe, "runtime", 10))
    ramp_time = int(conf(cijoe, "fio_ramp_time", 5))
    size = conf(cijoe, "fio_size", "100%")
    fio_device = str(pci_addr).replace(":", r"\:")
    return " ".join(
        [
            "fio",
            "--name=aisio-iommu-overhead",
            f"--filename={q(fio_device)}",
            "--ioengine=xnvme",
            "--xnvme_be=upcie",
            "--xnvme_dev_nsid=1",
            "--thread=1",
            "--direct=1",
            f"--rw={q(rw)}",
            f"--size={q(size)}",
            f"--bs={q(iosize)}",
            f"--iodepth={q(iodepth)}",
            "--time_based=1",
            f"--runtime={q(runtime)}",
            f"--ramp_time={q(ramp_time)}",
            "--norandommap=1",
            "--group_reporting=1",
            "--output-format=json",
            f"--percentile_list={FIO_PERCENTILE_LIST}",
            "--numjobs=1",
            "--cpus_allowed=0",
        ]
    )


def parse_xnvmeperf(output):
    match = re.search(
        r"^\s*Total:?\s+(?:[0-9,]+\s+)?(?P<iops>[0-9.]+)\s+"
        r"(?P<mibs>[0-9.]+)\s+(?P<failed>[0-9.]+)",
        output,
        re.MULTILINE,
    )
    if not match:
        raise ValueError("failed parsing xnvmeperf output")
    return {key: float(value) for key, value in match.groupdict().items()}


def parse_fio(output, rw):
    data = json.loads(output)
    job = data["jobs"][0]
    if int(job.get("error", 0)):
        raise ValueError(f"fio job failed with error {job['error']}")

    if rw not in RW_TO_OP:
        raise ValueError(f"unsupported rw={rw!r}; mixed workloads are not supported")
    stats = job[RW_TO_OP[rw]]
    percentiles = stats["clat_ns"]["percentile"]

    return {
        "iops": float(stats["iops"]),
        "mibs": float(stats.get("bw_bytes", 0)) / (1024 * 1024),
        "lat_ns": float(stats["lat_ns"]["mean"]),
        "tail_lat_ns": {
            name: float(percentiles[key]) for name, key in TAIL_LATENCIES.items()
        },
    }


def result_file(path, label, runner, rw, iosize, iodepth, rep):
    return path / (
        f"label_{label}-runner_{runner}-rw_{rw}-iosize_{iosize}-"
        f"iodepth_{iodepth}-rep_{rep}.json"
    )


def write_result(path, result):
    with path.open("x") as jfd:
        json.dump(result, jfd, indent=2)


def base_result(args, cijoe, runner, rw, iosize, iodepth, rep):
    return {
        "label": args.label,
        "driver": args.driver,
        "iommu": "on" if args.driver == "vfio-pci" else "off",
        "runner": runner,
        "rw": rw,
        "iosize": iosize,
        "iodepth": iodepth,
        "repeat": rep,
        "runtime": int(conf(cijoe, "runtime", 10)),
        "cpu": 0,
        "cpumask": cpu_to_cpumask(0),
        "fio_numjobs": 1,
        "fio_cpus_allowed": "0",
    }


def print_progress(done, total, action):
    print(f"{done}/{total}: {action}\033[K", end="\r", flush=True)


def main(args, cijoe):
    pci_addr = cijoe.getconf("filesystems.dset.pci_addr", None)
    mountpoint = cijoe.getconf("filesystems.dset.mountpoint", "/mnt/datasets")
    if not pci_addr:
        log.error("Missing filesystems.dset.pci_addr in config")
        return errno.EINVAL

    err = check_iommu_state(args, cijoe)
    if err:
        return err

    repeat = int(conf(cijoe, "repeat", 3))
    hugepages = int(conf(cijoe, "hugepages", 1024))
    workload_pause = int(conf(cijoe, "workload_pause", 5))
    cases = list(workload_cases(cijoe))
    out_dir = results_path(args)

    err = bind_driver(cijoe, args.driver, pci_addr, mountpoint, hugepages)
    if err:
        return err

    total = len(cases) * repeat * 2
    done = 0
    try:
        for case_idx, (rw, iosize, iodepth) in enumerate(cases, start=1):
            for rep in range(1, repeat + 1):
                workload = (
                    f"{args.label} {rw} iosize={iosize} " f"iodepth={iodepth} rep={rep}"
                )
                path = result_file(
                    out_dir, args.label, "xnvmeperf", rw, iosize, iodepth, rep
                )

                if path.exists():
                    done += 1
                    continue

                print_progress(done, total, f"running xnvmeperf {workload}")
                err, output = run_command(
                    cijoe, build_xnvmeperf_cmd(cijoe, pci_addr, rw, iosize, iodepth)
                )
                if err:
                    return err
                result = base_result(args, cijoe, "xnvmeperf", rw, iosize, iodepth, rep)
                result.update(parse_xnvmeperf(output))
                if result["failed"]:
                    log.error(f"xnvmeperf reported failed I/O: {result}")
                    return errno.EIO
                write_result(path, result)
                done += 1

            if workload_pause > 0 and case_idx < len(cases):
                time.sleep(workload_pause)

        for case_idx, (rw, iosize, iodepth) in enumerate(cases, start=1):
            for rep in range(1, repeat + 1):
                workload = (
                    f"{args.label} {rw} iosize={iosize} " f"iodepth={iodepth} rep={rep}"
                )
                path = result_file(out_dir, args.label, "fio", rw, iosize, iodepth, rep)

                if path.exists():
                    done += 1
                    continue

                print_progress(done, total, f"running fio {workload}")
                err, output = run_command(
                    cijoe, fio_cmd(cijoe, pci_addr, rw, iosize, iodepth)
                )
                if err:
                    return err
                result = base_result(args, cijoe, "fio", rw, iosize, iodepth, rep)
                result.update(parse_fio(output, rw))
                write_result(path, result)
                done += 1

            if workload_pause > 0 and case_idx < len(cases):
                time.sleep(workload_pause)

        print(f"{done}/{total}: complete")
    finally:
        reset_driver(cijoe, pci_addr)

    return 0
