"""
Configure and verify IOMMU boot mode
====================================

This script edits `/etc/default/grub` on the CIJOE target, regenerates the
boot loader config, and verifies the active boot mode after reboot.
"""

import errno
import logging as log
import os
import shlex
import tempfile
from argparse import ArgumentParser
from pathlib import Path

from iommu_common import cmdline_has_iommu_off, dmesg_indicates_iommu_enabled

GRUB_UPDATE_REMOTE = "/tmp/aisio-iommu-grub-update.py"
GRUB_UPDATE_SCRIPT = r"""
import re
import sys
from pathlib import Path

mode = sys.argv[1]
if mode not in ("on", "off"):
    raise SystemExit(f"unsupported mode: {mode}")

grub = Path("/etc/default/grub")
backup = Path("/etc/default/grub.aisio-iommu-overhead.bak")
text = grub.read_text()
if not backup.exists():
    backup.write_text(text)

cpuinfo = Path("/proc/cpuinfo").read_text(errors="ignore").lower()
vendor = "amd" if "authenticamd" in cpuinfo else "intel"
off_token = "amd_iommu=off" if vendor == "amd" else "intel_iommu=off"
on_token = "amd_iommu=on" if vendor == "amd" else "intel_iommu=on"

DROP_TOKENS = {
    "intel_iommu=off",
    "amd_iommu=off",
    "iommu=off",
    "intel_iommu=on",
    "amd_iommu=on",
}

def update_value(match):
    value = match.group("value").strip()
    tokens = [t for t in value.split() if t not in DROP_TOKENS]
    tokens.append(off_token if mode == "off" else on_token)
    return 'GRUB_CMDLINE_LINUX_DEFAULT="' + " ".join(tokens) + '"'

updated, count = re.subn(
    r'^GRUB_CMDLINE_LINUX_DEFAULT="(?P<value>[^"]*)"',
    update_value,
    text,
    count=1,
    flags=re.MULTILINE,
)
if count == 0:
    token = off_token if mode == "off" else on_token
    updated = text.rstrip() + '\nGRUB_CMDLINE_LINUX_DEFAULT="' + token + '"\n'

grub.write_text(updated)
"""


def add_args(parser: ArgumentParser):
    parser.add_argument(
        "--mode",
        choices=["set-off", "set-on", "verify-off", "verify-on"],
        required=True,
    )


def q(value):
    return shlex.quote(str(value))


def artifacts_path(args):
    path = Path(args.output) / "artifacts" / "iommu-overhead"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_target_file(cijoe, path):
    err, state = cijoe.run(f"cat {q(path)}")
    if err:
        return None, err
    return state.output(), 0


def detect_grub_update_command(cijoe):
    """Return the distro-appropriate command to regenerate grub config."""
    err, _ = cijoe.run("command -v update-grub")
    if not err:
        return "update-grub"
    err, _ = cijoe.run("command -v grub2-mkconfig")
    if not err:
        return "grub2-mkconfig -o /boot/grub2/grub.cfg"
    return None


def upload_grub_update_script(cijoe):
    fd, local = tempfile.mkstemp(suffix=".py", prefix="aisio-iommu-grub-")
    try:
        with os.fdopen(fd, "w") as fp:
            fp.write(GRUB_UPDATE_SCRIPT)
        if not cijoe.put(local, GRUB_UPDATE_REMOTE):
            return errno.EIO
    finally:
        os.unlink(local)
    return 0


def set_mode(args, cijoe, mode):
    artifacts = artifacts_path(args)
    before, _ = read_target_file(cijoe, "/etc/default/grub")
    if before is not None:
        (artifacts / f"grub-before-{mode}.txt").write_text(before)

    grub_update = detect_grub_update_command(cijoe)
    if grub_update is None:
        log.error("No update-grub or grub2-mkconfig found on target")
        return errno.ENOENT

    err = upload_grub_update_script(cijoe)
    if err:
        log.error("Failed transferring grub update script")
        return err

    cmd = f"python3 {GRUB_UPDATE_REMOTE} {q(mode)} && {grub_update}"
    err, state = cijoe.run(cmd)
    (artifacts / f"update-grub-{mode}.txt").write_text(state.output())
    if err:
        log.error(f"Failed updating grub for IOMMU {mode}: {state}")
        return err

    after, _ = read_target_file(cijoe, "/etc/default/grub")
    if after is not None:
        (artifacts / f"grub-after-{mode}.txt").write_text(after)

    return 0


def verify_mode(args, cijoe, mode):
    artifacts = artifacts_path(args)

    err, cmdline_state = cijoe.run("cat /proc/cmdline")
    if err:
        log.error(f"Failed reading /proc/cmdline: {cmdline_state}")
        return err
    cmdline = cmdline_state.output()

    err, dmesg_state = cijoe.run("dmesg | grep -i -E 'DMAR|IOMMU|AMD-Vi' || true")
    if err:
        log.error(f"Failed reading dmesg: {dmesg_state}")
        return err
    dmesg = dmesg_state.output()

    (artifacts / f"iommu-verify-{mode}.txt").write_text(
        f"=== /proc/cmdline ===\n{cmdline}\n=== dmesg ===\n{dmesg}"
    )

    off_in_cmdline = cmdline_has_iommu_off(cmdline)
    enabled_in_dmesg = dmesg_indicates_iommu_enabled(dmesg)

    if mode == "off":
        if not off_in_cmdline:
            log.error(
                "Expected IOMMU-off boot, but /proc/cmdline has no *_iommu=off token"
            )
            return errno.EINVAL
        if enabled_in_dmesg:
            log.error("Expected IOMMU-off boot, but dmesg indicates IOMMU is enabled")
            return errno.EINVAL
    else:
        if off_in_cmdline:
            log.error(
                "Expected IOMMU-on boot, but /proc/cmdline still has *_iommu=off token"
            )
            return errno.EINVAL
        if not enabled_in_dmesg:
            log.error(
                "Expected IOMMU-on boot, but dmesg does not indicate IOMMU is enabled"
            )
            return errno.EINVAL

    return 0


def main(args, cijoe):
    if args.mode == "set-off":
        return set_mode(args, cijoe, "off")
    if args.mode == "set-on":
        return set_mode(args, cijoe, "on")
    if args.mode == "verify-off":
        return verify_mode(args, cijoe, "off")
    if args.mode == "verify-on":
        return verify_mode(args, cijoe, "on")
    return errno.EINVAL
