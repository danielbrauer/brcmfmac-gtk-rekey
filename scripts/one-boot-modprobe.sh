#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

candidate="${1:?usage: $0 /absolute/path/to/brcmfmac-trace.ko state-directory}"
state_dir="${2:?usage: $0 /absolute/path/to/brcmfmac-trace.ko state-directory}"
shift 2

# Several udev workers can request this dependency concurrently. Serialize
# the complete load, not just marker consumption: otherwise a second worker
# can load stock while the first is still inserting the candidate.
exec 9>"$state_dir/load.lock"
flock -x 9
if [[ -d /sys/module/brcmfmac ]]; then
  exit 0
fi

if mv "$state_dir/armed" "$state_dir/attempted" 2>/dev/null; then
  cat /proc/sys/kernel/random/boot_id > "$state_dir/attempted-boot-id"
  /usr/sbin/insmod "$candidate" "$@"
  exit $?
fi

# The one-shot marker was already consumed, so every subsequent boot uses the
# distribution module even if the test boot crashed before cleanup ran.
/usr/sbin/modprobe --ignore-install brcmfmac
