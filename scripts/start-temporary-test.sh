#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

candidate="${1:?usage: $0 /absolute/path/to/brcmfmac-trace.ko [minutes]}"
minutes="${2:-45}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
expected_release="$(uname -r)"

if [[ "$candidate" != /* || ! -f "$candidate" ]]; then
  echo "candidate must be an existing file at an absolute path" >&2
  exit 2
fi

actual_release="$(modinfo -F vermagic "$candidate" | awk '{print $1}')"

if [[ "$actual_release" != "$expected_release" ]]; then
  echo "module release $actual_release does not match running kernel $expected_release" >&2
  exit 1
fi

if [[ ! "$minutes" =~ ^[1-9][0-9]*$ ]]; then
  echo "test duration must be a positive integer number of minutes" >&2
  exit 2
fi

systemctl stop brcmfmac-test-activate.service 2>/dev/null || true
systemctl stop brcmfmac-test-rollback.timer 2>/dev/null || true
systemctl stop brcmfmac-test-rollback.service 2>/dev/null || true
systemctl reset-failed brcmfmac-test-activate.service \
  brcmfmac-test-rollback.timer brcmfmac-test-rollback.service 2>/dev/null || true

systemd-run --unit=brcmfmac-test-rollback \
  --on-active="${minutes}m" \
  "$script_dir/rollback-temporary-module.sh"

systemd-run --unit=brcmfmac-test-activate --collect \
  "$script_dir/activate-temporary-module.sh" "$candidate"

echo "temporary test launched; stock-module rollback armed for ${minutes} minutes"
