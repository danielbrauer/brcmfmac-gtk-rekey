#!/usr/bin/env python3
"""Passive WPA2 header observer; never capture key data or write packet files."""
import argparse
import datetime
import json
import socket
import time

# Ethernet (14), EAPOL (4), fixed EAPOL-Key prefix through Key RSC (69).
# recvfrom stops here, before Key ID, MIC, and encrypted key data.
PREFIX_LENGTH = 87


class Observer:
    def __init__(self):
        self.highest_counter = None
        self.previous_group_rsc = None
        self.session = 0

    def observe(self, packet):
        if len(packet) < PREFIX_LENGTH or packet[12:14] != b"\x88\x8e":
            return None
        if packet[15] != 3 or packet[18] != 2:
            return None  # EAPOL-Key with RSN descriptor only.
        if int.from_bytes(packet[16:18], "big") < 95:
            return None
        info = int.from_bytes(packet[19:21], "big")
        pairwise, ack, mic = bool(info & 8), bool(info & 128), bool(info & 256)
        if not ack:
            return None
        if pairwise and not mic:
            self.session += 1
            self.highest_counter = None
            self.previous_group_rsc = None
            return {"kind": "pairwise_m1", "session": self.session}
        if not mic:
            return None
        counter = int.from_bytes(packet[23:31], "big")
        previous = self.highest_counter
        relation = ("first" if previous is None else
                    "greater" if counter > previous else
                    "equal" if counter == previous else "lower")
        self.highest_counter = counter if previous is None else max(counter, previous)
        rsc = int.from_bytes(packet[79:87], "little")
        result = {"kind": "pairwise_m3" if pairwise else "group_m1",
                  "session": self.session, "replay_relation": relation,
                  "key_rsc_zero": rsc == 0,
                  "encrypted_key_data": bool(info & 4096)}
        if not pairwise:
            result["rsc_matches_previous_group"] = (
                None if self.previous_group_rsc is None else
                rsc == self.previous_group_rsc)
            self.previous_group_rsc = rsc
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="wlan0")
    parser.add_argument("--seconds", type=int, default=1800)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("seconds must be between 1 and 3600")
    observer = Observer()
    deadline = time.monotonic() + args.seconds
    print(json.dumps({"event": "observer_started", "seconds": args.seconds}), flush=True)
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW,
                       socket.htons(0x888e)) as sock:
        sock.bind((args.interface, 0))
        sock.settimeout(1)
        while time.monotonic() < deadline:
            try:
                packet, address = sock.recvfrom(PREFIX_LENGTH)
            except socket.timeout:
                continue
            if address[2] == socket.PACKET_OUTGOING:
                continue
            result = observer.observe(packet)
            if result is not None:
                result["time"] = datetime.datetime.now().astimezone().isoformat()
                print(json.dumps(result), flush=True)
    print(json.dumps({"event": "observer_finished"}), flush=True)


if __name__ == "__main__":
    main()
