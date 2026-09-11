#!/bin/bash
# SPDX-FileCopyrightText: Samsung Electronics Co., Ltd
#
# SPDX-License-Identifier: BSD-3-Clause
set -u

echo "== tracefs =="
mount -t tracefs nodev /sys/kernel/debug/tracing 2> /dev/null || echo "(tracefs already mounted or refused)"

echo
echo "== available iommu tracepoint systems =="
ls -d /sys/kernel/debug/tracing/events/iommu /sys/kernel/debug/tracing/events/intel_iommu 2> /dev/null

echo
echo "== intel_iommu events =="
ls /sys/kernel/debug/tracing/events/intel_iommu 2> /dev/null

echo
echo "== iommu events =="
ls /sys/kernel/debug/tracing/events/iommu 2> /dev/null

echo
echo "== intel_iommu event formats =="
for e in /sys/kernel/debug/tracing/events/intel_iommu/*; do
  [ -d "$e" ] || continue
  echo "--- $(basename "$e") ---"
  sed -e 's/^\t//' "$e/format" 2> /dev/null | grep -E '^(name|ID|field|print_fmt)' | head -40
done

echo
echo "== iommu event formats =="
for e in /sys/kernel/debug/tracing/events/iommu/*; do
  [ -d "$e" ] || continue
  echo "--- $(basename "$e") ---"
  sed -e 's/^\t//' "$e/format" 2> /dev/null | grep -E '^(name|ID|field|print_fmt)' | head -40
done

echo
echo "== IOMMU groups =="
for g in /sys/kernel/iommu_groups/*; do
  [ -d "$g/devices" ] || continue
  echo "$(basename "$g"): $(ls "$g/devices" 2> /dev/null)"
done

echo
echo "== driver bind state (NVMe / NVIDIA) =="
lspci -k 2> /dev/null | grep -iE 'Non-Volatile|NVIDIA|Kernel driver' || echo "(no lspci or no matches)"
