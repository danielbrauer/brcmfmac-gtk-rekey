#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail

variant="${1:-trace}"
case "$variant" in
  trace|retry) ;;
  *) echo "usage: $0 {trace|retry}" >&2; exit 2 ;;
esac

kernel_version="6.18.39"
source_series="6.18"
package_version="6.18.39-1+rpt1"
kernel_release="6.18.39+rpt-rpi-v8"
archive_base="https://archive.raspberrypi.com/debian/pool/main/l/linux"
source_deb="linux-source-6.18_${package_version}_all.deb"
headers_deb="linux-headers-${kernel_release}_${package_version}_arm64.deb"
source_sha256="a44a2304ed372490bdfcbfbfe2e212c6285ed0cbf23a1fe8175905a716e5566e"
headers_sha256="e5e5619d9d048dd43ec5db90a09aeb563596a7b1c4d2bbeeae3f69cec1301813"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work_root="${RUNNER_TEMP:-$repo_root/build}/brcmfmac-${variant}"
package_root="$work_root/packages"
sysroot="$work_root/sysroot"
source_root="$work_root/linux"
driver_dir="$source_root/drivers/net/wireless/broadcom/brcm80211"
module_file="$driver_dir/brcmfmac/brcmfmac.ko"
output_dir="$repo_root/dist/$variant"

rm -rf "$work_root" "$output_dir"
mkdir -p "$package_root" "$sysroot" "$source_root" "$output_dir"

curl -fL "$archive_base/$source_deb" -o "$package_root/$source_deb"
curl -fL "$archive_base/$headers_deb" -o "$package_root/$headers_deb"
printf '%s  %s\n' "$source_sha256" "$package_root/$source_deb" | sha256sum -c -
printf '%s  %s\n' "$headers_sha256" "$package_root/$headers_deb" | sha256sum -c -

dpkg-deb -x "$package_root/$source_deb" "$sysroot"
dpkg-deb -x "$package_root/$headers_deb" "$sysroot"
tar -xf "$sysroot/usr/src/linux-source-${source_series}.tar.xz" \
  -C "$source_root" --strip-components=1

headers_root="$sysroot/usr/src/linux-headers-$kernel_release"
cp "$headers_root/.config" "$source_root/.config"
cp "$headers_root/Module.symvers" "$source_root/Module.symvers"
"$source_root/scripts/config" --file "$source_root/.config" \
  --set-str LOCALVERSION ""

git -C "$source_root" apply "$repo_root/patches/0001-brcmfmac-trace-key-slot-reuse.patch"
if [[ "$variant" == retry ]]; then
  git -C "$source_root" apply "$repo_root/patches/0002-brcmfmac-retry-reused-gtk-after-clear.patch"
  python3 "$repo_root/scripts/test-key-recovery.py" "$driver_dir/brcmfmac/cfg80211.c"
  python3 "$repo_root/scripts/test-firmware-status.py" "$driver_dir/brcmfmac/fwil.c"
  perl "$source_root/scripts/checkpatch.pl" --patch --strict --no-tree --no-signoff \
    "$repo_root/patches/0002-brcmfmac-retry-reused-gtk-after-clear.patch"
fi

make -C "$source_root" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
  LOCALVERSION=+rpt-rpi-v8 olddefconfig
make -C "$source_root" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
  LOCALVERSION=+rpt-rpi-v8 modules_prepare
make -C "$source_root" ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
  LOCALVERSION=+rpt-rpi-v8 \
  M="$driver_dir" modules

cp "$module_file" "$output_dir/brcmfmac-${variant}.ko"
printf '%s\n' "$kernel_release" > "$output_dir/kernel-release.txt"
sha256sum "$output_dir/brcmfmac-${variant}.ko" > "$output_dir/SHA256SUMS"
