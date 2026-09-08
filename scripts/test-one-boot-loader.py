#!/usr/bin/env python3
"""Exercise the actual loader script with isolated paths and fake module loaders."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.module = self.root / "loaded"
        self.boot = self.root / "boot-id"
        self.boot.write_text("boot-one\n")
        self.log = self.root / "calls"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        for kind in ("candidate", "stock"):
            script = self.bin / kind
            script.write_text("#!/bin/bash\n" +
                              f"printf '%s\\n' '{kind}' >> '{self.log}'\n" +
                              f"printf '%s\\n' \"$*\" >> '{self.root / (kind + '-args')}'\n" +
                              f"if [[ -e '{self.root / (kind + '-fail')}' ]]; then exit 1; fi\n" +
                              "sleep 0.15\n" + f"mkdir '{self.module}'\n")
            script.chmod(0o755)
        # Linux provides flock. macOS uses the same OS lock semantics through
        # a tiny test-only shim; the production script still calls util-linux.
        if not shutil.which("flock"):
            shim = self.bin / "flock"
            shim.write_text("#!/usr/bin/env python3\nimport fcntl, sys\n"
                            "fcntl.flock(int(sys.argv[-1]), fcntl.LOCK_EX)\n")
            shim.chmod(0o755)
        source = Path(__file__).with_name("one-boot-modprobe.sh").read_text()
        replacements = {
            "/sys/module/brcmfmac": str(self.module),
            "/proc/sys/kernel/random/boot_id": str(self.boot),
            "/usr/sbin/insmod": str(self.bin / "candidate"),
            "/usr/sbin/modprobe": str(self.bin / "stock"),
        }
        for original, isolated in replacements.items():
            self.assertIn(original, source)
            source = source.replace(original, isolated)
        self.loader = self.root / "loader.sh"
        self.loader.write_text(source)
        self.command = ["bash", str(self.loader), "/candidate.ko", str(self.state),
                        "roamoff=1", "feature_disable=0x282000"]

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def invoke(self):
        return subprocess.run(self.command, env=self.env, capture_output=True)

    def test_concurrent_requests_load_candidate_once(self):
        (self.state / "armed").touch()
        processes = [subprocess.Popen(self.command, env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for _ in range(12)]
        for process in processes:
            _, error = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, error.decode())
        self.assertEqual(self.calls(), ["candidate"])
        self.assertEqual((self.state / "attempted-boot-id").read_text(), "boot-one\n")
        self.assertEqual((self.root / "candidate-args").read_text().strip(),
                         "/candidate.ko roamoff=1 feature_disable=0x282000")

    def test_next_boot_uses_stock(self):
        (self.state / "armed").touch()
        self.assertEqual(self.invoke().returncode, 0)
        self.module.rmdir()
        self.boot.write_text("boot-two\n")
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual(self.calls(), ["candidate", "stock"])
        self.assertEqual((self.root / "stock-args").read_text().strip(),
                         "--ignore-install brcmfmac")

    def test_failed_candidate_is_not_retried(self):
        (self.state / "armed").touch()
        (self.root / "candidate-fail").touch()
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(self.invoke().returncode, 0)
        self.assertEqual(self.calls(), ["candidate", "stock"])

    def test_existing_module_does_not_consume_armed_marker(self):
        self.module.mkdir()
        (self.state / "armed").touch()
        self.assertEqual(self.invoke().returncode, 0)
        self.assertTrue((self.state / "armed").exists())
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
