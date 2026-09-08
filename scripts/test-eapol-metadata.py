#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "observer", Path(__file__).with_name("observe-eapol-metadata.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def frame(counter, rsc=0, pairwise=False, mic=True):
    packet = bytearray(87)
    packet[12:14] = b"\x88\x8e"
    packet[14:19] = bytes([2, 3, 0, 95, 2])
    info = 128 | (8 if pairwise else 0) | (256 if mic else 0) | 4096
    packet[19:21] = info.to_bytes(2, "big")
    packet[23:31] = counter.to_bytes(8, "big")
    packet[79:87] = rsc.to_bytes(8, "little")
    return bytes(packet)


class MetadataTest(unittest.TestCase):
    def test_replay_high_water_mark(self):
        observer = module.Observer()
        self.assertEqual([observer.observe(frame(n))["replay_relation"]
                          for n in [10, 11, 11, 9, 10, 12]],
                         ["first", "greater", "equal", "lower", "lower", "greater"])

    def test_distinct_counters(self):
        observer = module.Observer()
        observer.observe(frame(10, rsc=100))
        result = observer.observe(frame(11, rsc=0))
        self.assertEqual(result["replay_relation"], "greater")
        self.assertTrue(result["key_rsc_zero"])
        self.assertFalse(result["rsc_matches_previous_group"])

    def test_handshake_resets_observation(self):
        observer = module.Observer()
        observer.observe(frame(100))
        observer.observe(frame(1, pairwise=True, mic=False))
        self.assertEqual(observer.observe(frame(2, pairwise=True))["replay_relation"], "first")
        self.assertEqual(observer.observe(frame(3))["replay_relation"], "greater")

    def test_rejects_short_and_other_protocol(self):
        observer = module.Observer()
        self.assertIsNone(observer.observe(frame(1)[:86]))
        packet = bytearray(frame(1))
        packet[12:14] = b"\x08\x00"
        self.assertIsNone(observer.observe(packet))

    def test_output_has_no_raw_packet_or_counter(self):
        result = module.Observer().observe(frame(987654321, 123456789))
        self.assertEqual(set(result), {"kind", "session", "replay_relation",
                                      "key_rsc_zero", "encrypted_key_data",
                                      "rsc_matches_previous_group"})
        self.assertNotIn("987654321", str(result))
        self.assertNotIn("123456789", str(result))


if __name__ == "__main__":
    unittest.main()
