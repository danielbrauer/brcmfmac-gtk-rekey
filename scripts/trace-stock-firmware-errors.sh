#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Observe firmware error codes on the stock driver without enabling FIL dumps.
set -euo pipefail

duration="${1:-1500}"
[[ "$duration" =~ ^[0-9]+$ ]] && (( duration >= 1 && duration <= 3600 )) || {
  echo 'usage: trace-stock-firmware-errors.sh [seconds: 1..3600]' >&2
  exit 2
}
[[ "$EUID" == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ "$(uname -m)" == aarch64 ]] || { echo 'ARM64 only.' >&2; exit 1; }

trace_root=/sys/kernel/tracing
group="gtk_fwerr_$$"
instance="$trace_root/instances/$group"
event_created=0
cleanup() {
  if [[ -d "$instance" ]]; then
    echo 0 > "$instance/tracing_on" || true
    if [[ -e "$instance/events/$group/firmware_error/enable" ]]; then
      echo 0 > "$instance/events/$group/firmware_error/enable" || true
    fi
    rmdir "$instance" || true
  fi
  if (( event_created )); then
    echo "-:$group/firmware_error" >> "$trace_root/kprobe_events" || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

[[ -e "$trace_root/kprobe_events" ]] || {
  echo 'Mounted tracefs with kprobe events is required.' >&2
  exit 1
}
mkdir "$instance"
echo 0 > "$instance/tracing_on"
echo 64 > "$instance/buffer_size_kb"
# __brcmf_dbg(level, func, fmt, error_string, fwerr): only static strings
# and the numeric error argument are fetched. Never fetch data/key buffers.
# The filter retains only this precise fwil.c format, before buffer recording.
printf 'p:%s/firmware_error brcmfmac:__brcmf_dbg func=+0($arg2):string format=+0($arg3):string fwerr=%%x4:s32\n' "$group" >> "$trace_root/kprobe_events"
event_created=1
echo 'func == "brcmf_fil_cmd_data" && format ~ "Firmware error:*"' > "$instance/events/$group/firmware_error/filter"
echo 1 > "$instance/events/$group/firmware_error/enable"
echo 1 > "$instance/tracing_on"
printf 'Stock firmware-error trace started: %s, duration=%ss\n' "$(date --iso-8601=seconds)" "$duration"
sleep "$duration"
echo 0 > "$instance/tracing_on"
printf 'Stock firmware-error trace ended: %s\n' "$(date --iso-8601=seconds)"
cat "$instance/trace"
