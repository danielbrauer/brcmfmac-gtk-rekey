#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

candidate="${1:?usage: $0 /absolute/path/to/brcmfmac-trace.ko}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
rollback="$script_dir/rollback-temporary-module.sh"

is_loaded() {
  grep -q "^$1 " /proc/modules
}

for module in brcmfmac_wcc brcmfmac_cyw brcmfmac_bca; do
  if is_loaded "$module"; then
    modprobe -r "$module"
  fi
done

if is_loaded brcmfmac; then
  modprobe -r brcmfmac
fi

if ! insmod "$candidate"; then
  exec "$rollback"
fi

if ! modprobe brcmfmac_cyw; then
  echo "temporary brcmfmac loaded but Cypress/Infineon plugin did not; restoring stock" >&2
  exec "$rollback"
fi

for attempt in $(seq 1 24); do
  if nmcli -g GENERAL.STATE device show wlan0 2>/dev/null | grep -q '^100'; then
    exit 0
  fi
  nmcli device connect wlan0 >/dev/null 2>&1 || true
  sleep 5
done

echo "temporary brcmfmac loaded but wlan0 did not reconnect; restoring stock" >&2
exec "$rollback"
