#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

candidate="${1:?usage: $0 /absolute/path/to/brcmfmac-trace.ko state-directory}"
state_dir="${2:?usage: $0 /absolute/path/to/brcmfmac-trace.ko state-directory}"

if mv "$state_dir/armed" "$state_dir/attempted" 2>/dev/null; then
  cat /proc/sys/kernel/random/boot_id > "$state_dir/attempted-boot-id"
  exec /usr/sbin/insmod "$candidate"
fi

# The one-shot marker was already consumed, so every subsequent boot uses the
# distribution module even if the test boot crashed before cleanup ran.
exec /usr/sbin/modprobe --ignore-install brcmfmac
