#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

# This installs the exact artifact that passed the bounded live test.
release=6.18.39+rpt-rpi-v8
digest=13421cc55747df027a15a5d373d3ca1bce6a45179a682952f2db3a80cefdbf3c
source_version=EC29312C93DA66ACBD9464F
module_dir="/lib/modules/$release/updates/gtk-rekey"
module="$module_dir/brcmfmac.ko"
helper_dir=/usr/local/libexec/brcmfmac-gtk-rekey
helper="$helper_dir/manage-persistent-module"
state=/var/lib/brcmfmac-gtk-rekey
unit=brcmfmac-gtk-install-rollback
service="/etc/systemd/system/$unit.service"
timer="/etc/systemd/system/$unit.timer"

[[ "$EUID" == 0 ]] || { echo 'Run as root.' >&2; exit 1; }

check_digest() {
  [[ -f "$1" && ! -L "$1" ]] &&
    [[ "$(sha256sum "$1" | awk '{print $1}')" == "$digest" ]]
}

disarm() {
  systemctl disable --now "$unit.timer" 2>/dev/null || true
  rm -f "$service" "$timer" "$state/pending"
  systemctl daemon-reload
}

case "${1:-}" in
  install)
    candidate="${2:?usage: $0 install /absolute/path/to/tested-module.ko}"
    [[ "$(uname -r)" == "$release" ]] || {
      echo 'Running kernel does not match the tested artifact.' >&2; exit 1;
    }
    check_digest "$candidate" || {
      echo 'Candidate does not match the live-tested artifact.' >&2; exit 1;
    }
    [[ "$(modinfo -F vermagic "$candidate" | awk '{print $1}')" == "$release" ]]
    [[ "$(modinfo -F srcversion "$candidate")" == "$source_version" ]]
    [[ ! -e /etc/modprobe.d/brcmfmac-one-boot-test.conf ]]
    [[ ! -e "$module_dir" && ! -e "$state/pending" ]]
    [[ "$(modinfo -n brcmfmac)" == "/lib/modules/$release/kernel/"* ]] || {
      echo 'Another module override is already selected; reconcile it first.' >&2; exit 1;
    }
    test -x /usr/sbin/depmod
    test -x /usr/sbin/update-initramfs
    install -d -m 0755 "$helper_dir"
    install -m 0755 "${BASH_SOURCE[0]}" "$helper"
    # If any later step fails, restore module selection and the boot image.
    trap 'trap - ERR; "$helper" remove; exit 1' ERR
    install -d -m 0700 "$state"
    touch "$state/pending"
    cat > "$service" <<EOF
[Unit]
Description=Restore stock brcmfmac after an unconfirmed installation
ConditionPathExists=$state/pending

[Service]
Type=oneshot
ExecStart=$helper remove --reboot
EOF
    cat > "$timer" <<EOF
[Unit]
Description=Bound the first persistent brcmfmac boot

[Timer]
OnBootSec=15min
AccuracySec=1s
Unit=$unit.service

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    # Enable for the next boot, without starting an overdue timer now.
    systemctl enable "$unit.timer"
    install -d -m 0755 "$module_dir"
    install -m 0644 "$candidate" "$module_dir/.brcmfmac.ko.new"
    check_digest "$module_dir/.brcmfmac.ko.new"
    mv "$module_dir/.brcmfmac.ko.new" "$module"
    /usr/sbin/depmod -a "$release"
    /usr/sbin/update-initramfs -u -k "$release"
    [[ "$(modinfo -n brcmfmac)" == "$module" ]]
    check_digest "$module"
    trap - ERR
    echo 'Installed for the next boot; reboot, verify services, then confirm within 15 minutes.'
    ;;
  confirm)
    [[ "$(uname -r)" == "$release" ]]
    check_digest "$module"
    [[ "$(modinfo -n brcmfmac)" == "$module" ]]
    [[ "$(cat /sys/module/brcmfmac/srcversion)" == "$source_version" ]] || {
      echo 'The tested module is not loaded; rollback remains armed.' >&2; exit 1;
    }
    [[ -s /sys/module/brcmfmac/taint ]]
    disarm
    echo 'Persistent installation confirmed; automatic installation rollback removed.'
    ;;
  remove)
    # Never delete an artifact that no longer belongs to this installer.
    if [[ -e "$module" ]]; then
      check_digest "$module" || {
        echo 'Installed module changed; refusing to delete it.' >&2; exit 1;
      }
      rm "$module"
      rmdir "$module_dir"
    fi
    /usr/sbin/depmod -a "$release"
    /usr/sbin/update-initramfs -u -k "$release"
    disarm
    echo 'Stock module selection restored. Reboot to unload the patched module.'
    if [[ "${2:-}" == --reboot ]]; then
      systemctl reboot
    fi
    ;;
  *)
    echo "usage: $0 {install /absolute/path/to/tested-module.ko|confirm|remove [--reboot]}" >&2
    exit 2
    ;;
esac
