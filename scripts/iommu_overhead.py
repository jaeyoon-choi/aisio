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
VFIO_DEVICE_OPEN_RETRIES = 5
VFIO_DEVICE_OPEN_RETRY_DELAY = 2
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


def bdf_safe(pci_addr):
    return str(pci_addr).replace(":", "_").replace(".", "_")


def bdf_from_fio_filename(filename):
    return str(filename).replace("\\:", ":")


def configured_devices(cijoe):
    devices = cijoe.getconf("devices", [])
    if not devices:
        return []

    resolved = []
    for idx, device in enumerate(devices):
        pci_addr = device.get("pci_addr")
        if not pci_addr:
            raise ValueError(f"devices[{idx}] is missing pci_addr")

        resolved.append({"pci_addr": pci_addr, "cpu": idx})

    return resolved


def check_multi_cpu_capacity(cijoe, ndevices):
    err, state = cijoe.run("nproc")
    if err:
        log.error(f"Failed reading target CPU count: {state}")
        return err

    try:
        ncpus = int(state.output().strip().splitlines()[-1])
    except (IndexError, ValueError):
        log.error(f"Failed parsing target CPU count: {state.output()!r}")
        return errno.EINVAL

    if ncpus < ndevices:
        log.error(
            f"multi-device mode needs at least {ndevices} CPUs for per-device "
            f"pinning, but target reports {ncpus}"
        )
        return errno.EINVAL

    return 0


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


def transient_vfio_device_open_failure(output):
    markers = (
        "failed retrieving device handle, errno: -11",
        "vfio_group_get_device_fd(); errno(11)",
    )
    return any(marker in output for marker in markers)


def run_fio_multi(cijoe, cmd, driver):
    attempts = VFIO_DEVICE_OPEN_RETRIES if driver == "vfio-pci" else 1

    for attempt in range(1, attempts + 1):
        err, output = run_command(cijoe, cmd)
        if not err:
            return err, output

        if not transient_vfio_device_open_failure(output) or attempt == attempts:
            return err, output

        log.warning(
            "VFIO device open returned EAGAIN; retrying fio multi-device "
            f"run ({attempt}/{attempts})"
        )
        time.sleep(VFIO_DEVICE_OPEN_RETRY_DELAY)

    return errno.EAGAIN, ""


def bind_driver(cijoe, driver, pci_addrs, mountpoint, hugepages):
    if isinstance(pci_addrs, str):
        pci_addrs = [pci_addrs]

    commands = [
        "set -e",
        f"modprobe {q(driver)}",
        f"umount {q(mountpoint)} || true",
        f"sysctl -w vm.nr_hugepages={q(hugepages)}",
        "mkdir -p /dev/hugepages",
        "mountpoint -q /dev/hugepages || mount -t hugetlbfs nodev /dev/hugepages",
    ]
    commands.extend(
        f"devbind --device {q(pci_addr)} --bind {q(driver)}" for pci_addr in pci_addrs
    )
    return run_command(cijoe, "\n".join(commands))[0]


def reset_driver(cijoe, pci_addrs):
    if isinstance(pci_addrs, str):
        pci_addrs = [pci_addrs]

    cmd = "\n".join(
        f"devbind --device {q(pci_addr)} --bind nvme || true" for pci_addr in pci_addrs
    )
    err, _ = run_command(cijoe, cmd)
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


def fio_cmd_multi(cijoe, devices, rw, iosize, iodepth):
    runtime = int(conf(cijoe, "runtime", 10))
    ramp_time = int(conf(cijoe, "fio_ramp_time", 5))
    size = conf(cijoe, "fio_size", "100%")
    parts = [
        "fio",
        "--ioengine=xnvme",
        "--xnvme_be=upcie",
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
        "--output-format=json",
        f"--percentile_list={FIO_PERCENTILE_LIST}",
    ]

    for idx, device in enumerate(devices):
        fio_device = str(device["pci_addr"]).replace(":", r"\:")
        parts.extend(
            [
                f"--name=dev{idx}",
                f"--filename={q(fio_device)}",
                "--xnvme_dev_nsid=1",
                "--numjobs=1",
                f"--cpus_allowed={q(device['cpu'])}",
            ]
        )

    return " ".join(parts)


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


def parse_fio_multi(output, rw, devices):
    data = json.loads(output)
    jobs = data.get("jobs", [])
    if len(jobs) != len(devices):
        raise ValueError(
            f"fio returned {len(jobs)} jobs for {len(devices)} configured devices"
        )

    if rw not in RW_TO_OP:
        raise ValueError(f"unsupported rw={rw!r}; mixed workloads are not supported")

    devices_by_bdf = {device["pci_addr"]: device for device in devices}
    parsed = []
    seen = set()
    for job in jobs:
        if int(job.get("error", 0)):
            raise ValueError(f"fio job failed with error {job['error']}")

        opts = job.get("job options", job.get("job_options", {}))
        filename = opts.get("filename")
        if not filename:
            raise ValueError(f"fio job missing filename: jobname={job.get('jobname')}")

        bdf = bdf_from_fio_filename(filename)
        device = devices_by_bdf.get(bdf)
        if not device:
            raise ValueError(f"fio returned unexpected device filename: {filename}")
        if bdf in seen:
            raise ValueError(f"fio returned duplicate device filename: {filename}")
        seen.add(bdf)

        stats = job[RW_TO_OP[rw]]
        percentiles = stats["clat_ns"]["percentile"]
        parsed.append(
            (
                device,
                {
                    "iops": float(stats["iops"]),
                    "mibs": float(stats.get("bw_bytes", 0)) / (1024 * 1024),
                    "lat_ns": float(stats["lat_ns"]["mean"]),
                    "tail_lat_ns": {
                        name: float(percentiles[key])
                        for name, key in TAIL_LATENCIES.items()
                    },
                },
            )
        )

    return parsed


def result_file(path, label, runner, rw, iosize, iodepth, rep, devcount=None, dev=None):
    suffix = (
        f"label_{label}-runner_{runner}-rw_{rw}-iosize_{iosize}-" f"iodepth_{iodepth}"
    )
    if devcount is not None:
        suffix += f"-devcount_{devcount}"
    if dev is not None:
        suffix += f"-dev_{bdf_safe(dev)}"
    return path / f"{suffix}-rep_{rep}.json"


def write_result(path, result):
    with path.open("x") as jfd:
        json.dump(result, jfd, indent=2)


def base_result(
    args,
    cijoe,
    runner,
    rw,
    iosize,
    iodepth,
    rep,
    cpu=0,
    devcount=None,
    dev=None,
):
    result = {
        "label": args.label,
        "driver": args.driver,
        "iommu": "on" if args.driver == "vfio-pci" else "off",
        "runner": runner,
        "rw": rw,
        "iosize": iosize,
        "iodepth": iodepth,
        "repeat": rep,
        "runtime": int(conf(cijoe, "runtime", 10)),
        "cpu": int(cpu),
        "cpumask": cpu_to_cpumask(cpu),
        "fio_numjobs": 1,
        "fio_cpus_allowed": str(cpu),
    }
    if devcount is not None:
        result["devcount"] = int(devcount)
    if dev is not None:
        result["dev"] = dev
    return result


def print_progress(done, total, action):
    print(f"{done}/{total}: {action}\033[K", end="\r", flush=True)


def run_multi(args, cijoe, devices):
    mountpoint = cijoe.getconf("filesystems.dset.mountpoint", "/mnt/datasets")

    err = check_iommu_state(args, cijoe)
    if err:
        return err
    err = check_multi_cpu_capacity(cijoe, len(devices))
    if err:
        return err

    repeat = int(conf(cijoe, "repeat", 3))
    hugepages = int(conf(cijoe, "hugepages", 1024))
    workload_pause = int(conf(cijoe, "workload_pause", 5))
    cases = list(workload_cases(cijoe))
    out_dir = results_path(args)
    devcount = len(devices)

    err = bind_driver(
        cijoe,
        args.driver,
        [device["pci_addr"] for device in devices],
        mountpoint,
        hugepages,
    )
    if err:
        reset_driver(cijoe, [device["pci_addr"] for device in devices])
        return err

    total = len(cases) * repeat
    done = 0

    try:
        for case_idx, (rw, iosize, iodepth) in enumerate(cases, start=1):
            for rep in range(1, repeat + 1):
                workload = (
                    f"{args.label} {rw} iosize={iosize} "
                    f"iodepth={iodepth} devices={devcount} rep={rep}"
                )
                paths = [
                    result_file(
                        out_dir,
                        args.label,
                        "fio",
                        rw,
                        iosize,
                        iodepth,
                        rep,
                        devcount=devcount,
                        dev=device["pci_addr"],
                    )
                    for device in devices
                ]
                if all(path.exists() for path in paths):
                    done += 1
                    continue
                if any(path.exists() for path in paths):
                    log.error(f"partial fio result set exists for {workload}")
                    return errno.EEXIST

                print_progress(done, total, f"running fio {workload}")
                err, output = run_fio_multi(
                    cijoe,
                    fio_cmd_multi(cijoe, devices, rw, iosize, iodepth),
                    args.driver,
                )
                if err:
                    return err

                for device, parsed in parse_fio_multi(output, rw, devices):
                    result = base_result(
                        args,
                        cijoe,
                        "fio",
                        rw,
                        iosize,
                        iodepth,
                        rep,
                        cpu=device["cpu"],
                        devcount=devcount,
                        dev=device["pci_addr"],
                    )
                    result.update(parsed)
                    write_result(
                        result_file(
                            out_dir,
                            args.label,
                            "fio",
                            rw,
                            iosize,
                            iodepth,
                            rep,
                            devcount=devcount,
                            dev=device["pci_addr"],
                        ),
                        result,
                    )
                done += 1

            if workload_pause > 0 and case_idx < len(cases):
                time.sleep(workload_pause)

        print(f"{done}/{total}: complete")
    finally:
        reset_driver(cijoe, [device["pci_addr"] for device in devices])

    return 0


def main(args, cijoe):
    try:
        devices = configured_devices(cijoe)
    except ValueError as exc:
        log.error(str(exc))
        return errno.EINVAL
    if devices:
        return run_multi(args, cijoe, devices)

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
        reset_driver(cijoe, pci_addr)
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
