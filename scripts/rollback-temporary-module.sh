#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

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

modprobe brcmfmac
modprobe brcmfmac_cyw

for attempt in $(seq 1 24); do
  if nmcli -g GENERAL.STATE device show wlan0 2>/dev/null | grep -q '^100'; then
    exit 0
  fi
  nmcli device connect wlan0 >/dev/null 2>&1 || true
  sleep 5
done

echo "stock brcmfmac restored but wlan0 did not reconnect within 120 seconds" >&2
exit 1
