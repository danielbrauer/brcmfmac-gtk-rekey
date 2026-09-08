#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

candidate="${1:?usage: $0 /absolute/path/to/brcmfmac-trace.ko [minutes]}"
minutes="${2:-45}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
loader="$script_dir/one-boot-modprobe.sh"
cleanup="$script_dir/cleanup-one-boot-test.sh"
state_dir=/var/lib/brcmfmac-one-boot-test
modprobe_config=/etc/modprobe.d/brcmfmac-one-boot-test.conf
service_unit=/etc/systemd/system/brcmfmac-one-boot-cleanup.service
timer_unit=/etc/systemd/system/brcmfmac-one-boot-cleanup.timer
expected_release="$(uname -r)"

if [[ "$EUID" -ne 0 ]]; then
  echo "run this script as root" >&2
  exit 2
fi

if [[ "$candidate" != /* || ! -f "$candidate" ]]; then
  echo "candidate must be an existing file at an absolute path" >&2
  exit 2
fi

if [[ ! "$minutes" =~ ^[1-9][0-9]*$ ]]; then
  echo "test duration must be a positive integer number of minutes" >&2
  exit 2
fi

# modprobe install commands are whitespace-delimited. Refuse paths that would
# need shell quoting instead of trying to generate a fragile command.
if [[ "$candidate" =~ [^A-Za-z0-9_./+-] || "$loader" =~ [^A-Za-z0-9_./+-] ]]; then
  echo "candidate and loader paths must contain only safe path characters" >&2
  exit 2
fi

actual_release="$(modinfo -F vermagic "$candidate" | awk '{print $1}')"
if [[ "$actual_release" != "$expected_release" ]]; then
  echo "module release $actual_release does not match running kernel $expected_release" >&2
  exit 1
fi

if [[ -e "$state_dir/armed" || -e "$state_dir/attempted" ]]; then
  echo "a one-boot test is already armed or awaiting cleanup" >&2
  exit 1
fi

install -d -m 0700 "$state_dir"
printf 'install brcmfmac %s %s %s $CMDLINE_OPTS\n' "$loader" "$candidate" "$state_dir" \
  > "$modprobe_config"

printf '%s\n' \
  '[Unit]' \
  'Description=Clean up one-boot brcmfmac test' \
  'ConditionPathExists=/var/lib/brcmfmac-one-boot-test/attempted-boot-id' \
  '' \
  '[Service]' \
  'Type=oneshot' \
  "ExecStart=$cleanup" \
  > "$service_unit"

printf '%s\n' \
  '[Unit]' \
  'Description=Return a one-boot brcmfmac test to the stock driver' \
  '' \
  '[Timer]' \
  "OnBootSec=${minutes}min" \
  'AccuracySec=1s' \
  'Unit=brcmfmac-one-boot-cleanup.service' \
  '' \
  '[Install]' \
  'WantedBy=timers.target' \
  > "$timer_unit"

systemctl daemon-reload
systemctl enable brcmfmac-one-boot-cleanup.timer
touch "$state_dir/armed"

echo "one-boot test armed for the next boot; reboot to begin"
