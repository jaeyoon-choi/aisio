"""
Collect kernel NVMe IOMMU overhead benchmark results with raw fio.
"""

import errno
import json
import logging as log
import shlex
import time
from argparse import ArgumentParser
from pathlib import Path

from iommu_common import dmesg_indicates_iommu_enabled

FIO_PERCENTILE_LIST = "99.9:99.99:99.999"
BLOCKDEV_RETRIES = 30
BLOCKDEV_RETRY_DELAY = 1
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
    parser.add_argument("--label", choices=["off", "on"], required=True)


def q(value):
    return shlex.quote(str(value))


def conf(cijoe, key, default=None):
    return cijoe.getconf(f"iommu_overhead.{key}", default)


def cpu_to_cpumask(cpu):
    return hex(1 << int(cpu))


def bdf_safe(pci_addr):
    return str(pci_addr).replace(":", "_").replace(".", "_")


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
            f"fio_4k_page mode needs at least {ndevices} CPUs for per-device "
            f"pinning, but target reports {ncpus}"
        )
        return errno.EINVAL

    return 0


def check_iommu_state(args, cijoe):
    cmd = "cat /proc/cmdline; echo; dmesg | grep -i -E 'DMAR|IOMMU|AMD-Vi' || true"
    err, state = cijoe.run(cmd)
    if err:
        log.error(f"Failed reading IOMMU state: {state}")
        return err

    enabled = dmesg_indicates_iommu_enabled(state.output())
    expected = args.label == "on"
    if enabled != expected:
        mode = "enabled" if expected else "disabled"
        log.error(f"{args.label} requires IOMMU {mode}; refusing to overwrite results")
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


def run_command(cijoe, cmd, log_error=True):
    err, state = cijoe.run(cmd)
    if err and log_error:
        log.error(f"Failed command: {state}")
    return err, state.output()


def ensure_nvme_commands(pci_addrs):
    commands = []
    for pci_addr in pci_addrs:
        commands.extend(
            [
                f"dev={q(pci_addr)}",
                'driver="$(basename "$(readlink -f "/sys/bus/pci/devices/${dev}/driver" 2>/dev/null)" 2>/dev/null || true)"',
                'if [ "${driver}" != "nvme" ]; then',
                '  devbind --device "${dev}" --bind nvme',
                "fi",
            ]
        )
    return commands


def bind_nvme(cijoe, pci_addrs, mountpoint):
    if isinstance(pci_addrs, str):
        pci_addrs = [pci_addrs]

    commands = [
        "set -e",
        "modprobe nvme",
        f"umount {q(mountpoint)} || true",
        "mountpoint -q /dev/hugepages && umount /dev/hugepages || true",
        "sysctl -w vm.nr_hugepages=0",
    ]
    if bool(conf(cijoe, "disable_thp", False)):
        commands.extend(
            [
                "test ! -w /sys/kernel/mm/transparent_hugepage/enabled || "
                "echo never > /sys/kernel/mm/transparent_hugepage/enabled",
                "test ! -w /sys/kernel/mm/transparent_hugepage/defrag || "
                "echo never > /sys/kernel/mm/transparent_hugepage/defrag",
            ]
        )

    commands.extend(ensure_nvme_commands(pci_addrs))
    commands.append("udevadm settle || true")
    return run_command(cijoe, "\n".join(commands))[0]


def reset_driver(cijoe, pci_addrs):
    if isinstance(pci_addrs, str):
        pci_addrs = [pci_addrs]

    cmd = "\n".join(ensure_nvme_commands(pci_addrs))
    err, _ = run_command(cijoe, cmd)
    return err


def blockdev_resolve_cmd(pci_addr):
    return "\n".join(
        [
            f"bdf={q(pci_addr)}",
            'devpath="/sys/bus/pci/devices/${bdf}"',
            "emit_block() {",
            '  name="$1"',
            '  test -n "${name}" || return 1',
            '  test -b "/dev/${name}" || return 1',
            '  echo "/dev/${name}"',
            "  exit 0",
            "}",
            'for ns in "${devpath}"/nvme/nvme*/nvme*n*; do',
            '  test -e "${ns}" || continue',
            '  emit_block "$(basename "${ns}")"',
            "done",
            'for ctrl in "${devpath}"/nvme/nvme*; do',
            '  test -e "${ctrl}" || continue',
            '  ctrlname="$(basename "${ctrl}")"',
            '  for block in /sys/block/"${ctrlname}"n*; do',
            '    test -e "${block}" || continue',
            '    emit_block "$(basename "${block}")"',
            "  done",
            "done",
            'devreal="$(readlink -f "${devpath}")"',
            "for block in /sys/block/nvme*n*; do",
            '  test -e "${block}" || continue',
            '  blockreal="$(readlink -f "${block}")" || continue',
            '  case "${blockreal}" in "${devreal}"/*) ;; *) continue ;; esac',
            '  emit_block "$(basename "${block}")"',
            "done",
            'echo "devpath=${devpath}"',
            'echo "devreal=${devreal}"',
            'echo "controllers:"',
            'ls -l "${devpath}"/nvme 2>/dev/null || true',
            'echo "block devices:"',
            "ls -l /sys/block/nvme*n* 2>/dev/null || true",
            "exit 1",
        ]
    )


def resolve_blockdev(cijoe, pci_addr):
    cmd = blockdev_resolve_cmd(pci_addr)
    last_output = ""
    for _ in range(BLOCKDEV_RETRIES):
        err, output = run_command(cijoe, cmd, log_error=False)
        last_output = output
        if not err:
            return output.strip().splitlines()[-1], 0
        time.sleep(BLOCKDEV_RETRY_DELAY)

    log.error(f"Failed resolving NVMe block device for {pci_addr}")
    log.error(f"Resolver command:\n{cmd}")
    if last_output:
        log.error(f"Resolver output:\n{last_output}")
    return None, errno.ENOENT


def resolve_block_devices(cijoe, devices):
    resolved = []
    for device in devices:
        blockdev, err = resolve_blockdev(cijoe, device["pci_addr"])
        if err:
            return [], err

        item = dict(device)
        item["blockdev"] = blockdev
        resolved.append(item)

    return resolved, 0


def fio_cmd(cijoe, devices, rw, iosize, iodepth):
    runtime = int(conf(cijoe, "runtime", 10))
    ramp_time = int(conf(cijoe, "fio_ramp_time", 5))
    size = conf(cijoe, "fio_size", "100%")
    parts = [
        "fio",
        "--ioengine=io_uring",
        "--thread=1",
        "--direct=1",
        "--mem=malloc",
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
        parts.extend(
            [
                f"--name=dev{idx}",
                f"--filename={q(device['blockdev'])}",
                "--numjobs=1",
                f"--cpus_allowed={q(device['cpu'])}",
            ]
        )

    return " ".join(parts)


def parse_fio_multi(output, rw, devices):
    data = json.loads(output)
    jobs = data.get("jobs", [])
    if len(jobs) != len(devices):
        raise ValueError(
            f"fio returned {len(jobs)} jobs for {len(devices)} configured devices"
        )

    if rw not in RW_TO_OP:
        raise ValueError(f"unsupported rw={rw!r}; mixed workloads are not supported")

    devices_by_name = {device["blockdev"]: device for device in devices}
    parsed = []
    seen = set()
    for job in jobs:
        if int(job.get("error", 0)):
            raise ValueError(f"fio job failed with error {job['error']}")

        opts = job.get("job options", job.get("job_options", {}))
        filename = opts.get("filename")
        if not filename:
            raise ValueError(f"fio job missing filename: jobname={job.get('jobname')}")

        device = devices_by_name.get(filename)
        if not device:
            raise ValueError(f"fio returned unexpected device filename: {filename}")
        if filename in seen:
            raise ValueError(f"fio returned duplicate device filename: {filename}")
        seen.add(filename)

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


def result_file(path, label, runner, rw, iosize, iodepth, rep, devcount, dev):
    suffix = (
        f"label_{label}-runner_{runner}-rw_{rw}-iosize_{iosize}-"
        f"iodepth_{iodepth}-devcount_{devcount}-dev_{bdf_safe(dev)}"
    )
    return path / f"{suffix}-rep_{rep}.json"


def write_result(path, result):
    with path.open("x") as jfd:
        json.dump(result, jfd, indent=2)


def base_result(args, cijoe, rw, iosize, iodepth, rep, device, devcount):
    cpu = device["cpu"]
    return {
        "label": args.label,
        "driver": "nvme",
        "iommu": args.label,
        "runner": "fio",
        "rw": rw,
        "iosize": iosize,
        "iodepth": iodepth,
        "repeat": rep,
        "runtime": int(conf(cijoe, "runtime", 10)),
        "cpu": int(cpu),
        "cpumask": cpu_to_cpumask(cpu),
        "fio_numjobs": 1,
        "fio_cpus_allowed": str(cpu),
        "devcount": int(devcount),
        "dev": device["pci_addr"],
        "blockdev": device["blockdev"],
        "backend": "fio_4k_page",
        "ioengine": "io_uring",
        "fio_mem": "malloc",
        "hugepages": 0,
        "page_mode": "normal_4k",
    }


def print_progress(done, total, action):
    print(f"{done}/{total}: {action}\033[K", end="\r", flush=True)


def run(args, cijoe, devices):
    mountpoint = cijoe.getconf("filesystems.dset.mountpoint", "/mnt/datasets")

    err = check_iommu_state(args, cijoe)
    if err:
        return err
    err = check_multi_cpu_capacity(cijoe, len(devices))
    if err:
        return err

    repeat = int(conf(cijoe, "repeat", 3))
    workload_pause = int(conf(cijoe, "workload_pause", 5))
    cases = list(workload_cases(cijoe))
    out_dir = results_path(args)
    devcount = len(devices)
    pci_addrs = [device["pci_addr"] for device in devices]

    err = bind_nvme(cijoe, pci_addrs, mountpoint)
    if err:
        reset_driver(cijoe, pci_addrs)
        return err

    devices, err = resolve_block_devices(cijoe, devices)
    if err:
        reset_driver(cijoe, pci_addrs)
        return err

    total = len(cases) * repeat
    done = 0

    try:
        for case_idx, (rw, iosize, iodepth) in enumerate(cases, start=1):
            for rep in range(1, repeat + 1):
                workload = (
                    f"{args.label} fio_4k_page {rw} iosize={iosize} "
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
                        devcount,
                        device["pci_addr"],
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
                err, output = run_command(
                    cijoe, fio_cmd(cijoe, devices, rw, iosize, iodepth)
                )
                if err:
                    return err

                for device, parsed in parse_fio_multi(output, rw, devices):
                    result = base_result(
                        args, cijoe, rw, iosize, iodepth, rep, device, devcount
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
                            devcount,
                            device["pci_addr"],
                        ),
                        result,
                    )
                done += 1

            if workload_pause > 0 and case_idx < len(cases):
                time.sleep(workload_pause)

        print(f"{done}/{total}: complete")
    finally:
        reset_driver(cijoe, pci_addrs)

    return 0


def main(args, cijoe):
    try:
        devices = configured_devices(cijoe)
    except ValueError as exc:
        log.error(str(exc))
        return errno.EINVAL

    if not devices:
        pci_addr = cijoe.getconf("filesystems.dset.pci_addr", None)
        if not pci_addr:
            log.error("Missing filesystems.dset.pci_addr in config")
            return errno.EINVAL
        devices = [{"pci_addr": pci_addr, "cpu": 0}]

    return run(args, cijoe, devices)
