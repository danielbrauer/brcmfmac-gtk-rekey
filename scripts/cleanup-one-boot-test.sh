#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

state_dir=/var/lib/brcmfmac-one-boot-test
modprobe_config=/etc/modprobe.d/brcmfmac-one-boot-test.conf
service_unit=/etc/systemd/system/brcmfmac-one-boot-cleanup.service
timer_unit=/etc/systemd/system/brcmfmac-one-boot-cleanup.timer
current_boot_id="$(cat /proc/sys/kernel/random/boot_id)"
attempted_boot_id="$(cat "$state_dir/attempted-boot-id" 2>/dev/null || true)"

rm -f "$modprobe_config" \
  "$state_dir/armed" "$state_dir/attempted" "$state_dir/attempted-boot-id"
systemctl disable --now brcmfmac-one-boot-cleanup.timer 2>/dev/null || true
rm -f "$service_unit" "$timer_unit"
systemctl daemon-reload

if [[ -n "$attempted_boot_id" && "$attempted_boot_id" == "$current_boot_id" ]]; then
  systemctl reboot
fi
