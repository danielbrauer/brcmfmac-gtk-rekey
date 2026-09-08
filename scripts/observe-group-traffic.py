#!/usr/bin/env python3
"""Count delivered group Ethernet headers; never capture payloads or addresses."""
import argparse
import datetime
import json
import socket
import time

# Linux UAPI packet type; explicit value keeps the pure parser testable on macOS.
PACKET_OUTGOING = 4


class Counts:
    def __init__(self):
        self.broadcast = 0
        self.multicast = 0
        self.unicast = 0

    def observe(self, header, packet_type):
        if len(header) != 14 or packet_type == PACKET_OUTGOING:
            return
        if header[12:14] == b"\x88\x8e":
            return  # Handshake delivery is not evidence of group-data reception.
        if header[:6] == b"\xff" * 6:
            self.broadcast += 1
        elif header[0] & 1:
            self.multicast += 1
        else:
            self.unicast += 1

    def result(self):
        return {"broadcast": self.broadcast, "multicast": self.multicast,
                "unicast": self.unicast}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", default="wlan0")
    parser.add_argument("--seconds", type=int, default=2700)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("seconds must be between 1 and 3600")
    counts = Counts()
    start = time.monotonic()
    deadline = start + args.seconds
    next_report = min(start + 30, deadline)
    print(json.dumps({"event": "group_observer_started", "seconds": args.seconds}), flush=True)
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)) as sock:
        sock.bind((args.interface, 0))
        sock.settimeout(1)
        while time.monotonic() < deadline:
            try:
                header, address = sock.recvfrom(14)
                counts.observe(header, address[2])
            except socket.timeout:
                pass
            now = time.monotonic()
            if now >= next_report:
                result = counts.result()
                result["elapsed_seconds"] = round(now - start)
                result["time"] = datetime.datetime.now().astimezone().isoformat()
                print(json.dumps(result), flush=True)
                counts = Counts()
                next_report = min(now + 30, deadline)
    print(json.dumps({"event": "group_observer_finished"}), flush=True)


if __name__ == "__main__":
    main()
