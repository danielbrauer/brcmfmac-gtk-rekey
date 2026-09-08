#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "group_observer", Path(__file__).with_name("observe-group-traffic.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def header(destination, protocol=b"\x08\x00"):
    return destination + bytes(6) + protocol


class GroupTrafficTest(unittest.TestCase):
    def test_group_and_unicast_classification(self):
        counts = module.Counts()
        counts.observe(header(b"\xff" * 6), 1)
        counts.observe(header(bytes([1, 0, 0, 0, 0, 1])), 2)
        counts.observe(header(bytes([2, 0, 0, 0, 0, 1])), 0)
        self.assertEqual(counts.result(), {"broadcast": 1, "multicast": 1, "unicast": 1})

    def test_outgoing_short_and_handshake_excluded(self):
        counts = module.Counts()
        counts.observe(header(b"\xff" * 6), module.PACKET_OUTGOING)
        counts.observe(bytes(13), 1)
        counts.observe(header(b"\xff" * 6, b"\x88\x8e"), 1)
        self.assertEqual(sum(counts.result().values()), 0)


if __name__ == "__main__":
    unittest.main()
