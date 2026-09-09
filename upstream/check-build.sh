#!/usr/bin/env bash
# Build a disposable Linux checkout; never install or boot its output.
set -euo pipefail
series_dir=$(cd -- "$(dirname -- "$0")" && pwd)
kernel=$(cd -- "${1:?usage: check-build.sh DISPOSABLE_KERNEL_CHECKOUT}" && pwd)
: "${ARCH:?set ARCH}" "${DRIVER_MODE:?set DRIVER_MODE to y or m}"
: "${DRIVER_DEBUG:?set DRIVER_DEBUG to y or n}"
case "$DRIVER_MODE:$DRIVER_DEBUG" in [ym]:[yn]) ;; *) exit 2 ;; esac
export ARCH CROSS_COMPILE="${CROSS_COMPILE:-}"
results="$series_dir/results"
build="$kernel/build-upstream"
mkdir -p "$results"
test "$(git -C "$kernel" rev-parse HEAD)" = "$(cat "$series_dir/base-commit")"
test -z "$(git -C "$kernel" status --porcelain)"
cd "$kernel"
make O="$build" allnoconfig
config=(scripts/config --file "$build/.config")
"${config[@]}" -e EXPERT -e MODULES -e NET -e INET -e NETDEVICES \
  -e WIRELESS -e WLAN -e WLAN_VENDOR_BROADCOM -e MMC -e PCI \
  -e USB_SUPPORT -e USB -d WERROR
if [[ $ARCH == x86_64 ]]; then "${config[@]}" -e 64BIT; fi
if [[ $DRIVER_MODE == m ]]; then
  "${config[@]}" -m CFG80211 -m BRCMFMAC
else
  "${config[@]}" -e CFG80211 -e BRCMFMAC
fi
"${config[@]}" -e BRCMFMAC_SDIO -e BRCMFMAC_USB -e BRCMFMAC_PCIE
if [[ $DRIVER_DEBUG == y ]]; then
  "${config[@]}" -e SMP -e DEBUG_KERNEL -e BRCMDBG -e FTRACE \
    -e FUNCTION_TRACER -e BRCM_TRACING
else
  "${config[@]}" -d SMP -d BRCMDBG -d BRCM_TRACING
fi
make O="$build" olddefconfig
for expected in "CONFIG_BRCMFMAC=$DRIVER_MODE" CONFIG_BRCMFMAC_SDIO=y \
  CONFIG_BRCMFMAC_USB=y CONFIG_BRCMFMAC_PCIE=y; do
  grep -Fx "$expected" "$build/.config"
done
if [[ $DRIVER_DEBUG == y ]]; then
  grep -Fx CONFIG_BRCMDBG=y "$build/.config"
  grep -Fx CONFIG_BRCM_TRACING=y "$build/.config"
fi
cp "$build/.config" "$results/config"
"${CROSS_COMPILE}gcc" --version > "$results/compiler.txt"
sparse --version > "$results/sparse-version.txt" 2>&1
path=drivers/net/wireless/broadcom/brcm80211/brcmfmac
build_stage() {
  local stage=$1
  make -j"$(nproc)" O="$build" W=1 vmlinux modules 2>&1 | tee "$results/$stage-build.log"
  # Recompile the changed units with sparse and strict compiler diagnostics.
  touch "$path/cfg80211.c" "$path/fwil.c"
  make -j"$(nproc)" O="$build" W=1 KCFLAGS=-Werror C=2 \
    "$path/cfg80211.o" "$path/fwil.o" 2>&1 | tee "$results/$stage-analysis.log"
  "${CROSS_COMPILE}objdump" -d "$build/$path/cfg80211.o" \
    "$build/$path/fwil.o" | perl scripts/checkstack.pl "${ARCH/x86_64/x86}" \
    > "$results/$stage-stack.txt"
}
build_stage base
number=0
while IFS= read -r patch; do
  number=$((number + 1))
  perl scripts/checkpatch.pl --no-signoff "$series_dir/$patch" | tee "$results/$number-style.txt"
  # Record the full check too: unsigned RFCs must report the missing DCO tag.
  perl scripts/checkpatch.pl "$series_dir/$patch" > "$results/$number-full-checkpatch.txt" || true
  perl scripts/get_maintainer.pl --no-git --no-git-fallback "$series_dir/$patch" \
    > "$results/$number-maintainers.txt"
  git -c user.name='RFC validation' -c user.email='validation@example.invalid' \
    -c commit.gpgsign=false am "$series_dir/$patch"
  build_stage "$number"
done < "$series_dir/series"
python3 "$series_dir/../scripts/test-firmware-status.py" "$path/fwil.c" | tee "$results/status-tests.txt"
python3 "$series_dir/../scripts/test-key-recovery.py" "$path/cfg80211.c" | tee "$results/recovery-tests.txt"
perl scripts/kernel-doc -none "$path/fwil.c" 2>&1 | tee "$results/kernel-doc.txt"
python3 - "$results" <<'CHECK'
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])
def warnings(stage):
    lines = (root / f"{stage}-build.log").read_text().splitlines()
    lines += (root / f"{stage}-analysis.log").read_text().splitlines()
    return {re.sub(r":\d+(?::\d+)?:", ":LINE:", line)
            for line in lines if "warning:" in line or "error:" in line}
baseline = warnings("base")
for stage in ("1", "2"):
    added = warnings(stage) - baseline
    if added:
        raise SystemExit("New diagnostics:\n" + "\n".join(sorted(added)))
    full = (root / f"{stage}-full-checkpatch.txt").read_text()
    assert "ERROR: Missing Signed-off-by: line(s)" in full
    assert "total: 1 errors, 0 warnings, 0 checks" in full
assert not (root / "kernel-doc.txt").read_text().strip()
print("Base and both patches built; no new compiler/sparse diagnostics.")
print("Full checkpatch reports only the deliberately missing human sign-off.")
CHECK
