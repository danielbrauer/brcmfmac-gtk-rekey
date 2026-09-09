"""Exercise the installer against a fake root; never touch host system files."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).with_name('manage-persistent-module.sh').read_text()
RELEASE = '6.18.39+rpt-rpi-v8'
VERSION = 'EC29312C93DA66ACBD9464F'
ARTIFACT = b'tested module fixture\n'


class PersistentInstall(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.module = self.root / f'lib/modules/{RELEASE}/updates/gtk-rekey/brcmfmac.ko'
        self.stock = self.root / f'lib/modules/{RELEASE}/kernel/brcmfmac.ko'
        self.stock.parent.mkdir(parents=True)
        self.stock.write_bytes(b'untouched stock')
        self.pending = self.root / 'var/lib/brcmfmac-gtk-rekey/pending'
        self.timer = self.root / 'etc/systemd/system/brcmfmac-gtk-install-rollback.timer'
        self.timer.parent.mkdir(parents=True)
        self.loaded = self.root / 'sys/module/brcmfmac/srcversion'
        self.loaded.parent.mkdir(parents=True)
        self.loaded.write_text('stock')
        self.loaded.with_name('taint').write_text('O')
        self.candidate = self.root / 'candidate.ko'
        self.candidate.write_bytes(ARTIFACT)
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        GTK_TEST_ROOT=str(self.root))
        stub = '''#!/usr/bin/env python3
import hashlib, os, pathlib, sys
r=pathlib.Path(os.environ['GTK_TEST_ROOT'])
name=pathlib.Path(sys.argv[0]).name
a=sys.argv[1:]
with (r/'commands').open('a') as f: f.write(name+' '+' '.join(a)+'\\n')
if name == 'uname': print('6.18.39+rpt-rpi-v8')
elif name == 'sha256sum': print(hashlib.sha256(pathlib.Path(a[0]).read_bytes()).hexdigest(),a[0])
elif name == 'modinfo':
 if a[:2] == ['-F','vermagic']: print('6.18.39+rpt-rpi-v8 SMP')
 elif a[:2] == ['-F','srcversion']: print('EC29312C93DA66ACBD9464F')
 elif a[0] == '-n':
  m=r/'lib/modules/6.18.39+rpt-rpi-v8/updates/gtk-rekey/brcmfmac.ko'
  print(m if m.exists() else r/'lib/modules/6.18.39+rpt-rpi-v8/kernel/brcmfmac.ko')
elif name == 'update-initramfs' and (r/'fail-update').exists():
 (r/'fail-update').unlink()
 sys.exit(1)
'''
        for name in ['uname', 'sha256sum', 'modinfo', 'systemctl', 'depmod', 'update-initramfs']:
            p = self.bin / name
            p.write_text(stub)
            p.chmod(0o755)
        script = SOURCE.replace('[[ "$EUID" == 0 ]]', 'true')
        script = script.replace('13421cc55747df027a15a5d373d3ca1bce6a45179a682952f2db3a80cefdbf3c', hashlib.sha256(ARTIFACT).hexdigest())
        for prefix in ['/lib/modules', '/usr/local/libexec', '/var/lib', '/etc', '/sys/module']:
            script = script.replace(prefix, str(self.root) + prefix)
        script = script.replace('/usr/sbin/', str(self.bin) + '/')
        self.script = self.root / 'manage.sh'
        self.script.write_text(script)
        self.script.chmod(0o755)

    def run_mode(self, *args, success=True):
        p = subprocess.run(['bash', str(self.script), *map(str, args)], env=self.env,
                           capture_output=True, text=True)
        if success:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.stock.read_bytes(), b'untouched stock')

    def test_wrong_artifact_does_not_install(self):
        self.candidate.write_bytes(b'wrong')
        self.run_mode('install', self.candidate, success=False)
        self.assertFalse(self.module.exists())
        self.assertFalse(self.pending.exists())

    def test_install_arms_next_boot_without_starting_overdue_timer(self):
        self.run_mode('install', self.candidate)
        self.assertEqual(self.module.read_bytes(), ARTIFACT)
        self.assertTrue(self.pending.exists())
        self.assertIn('OnBootSec=15min', self.timer.read_text())
        commands = (self.root / 'commands').read_text()
        self.assertIn('systemctl enable brcmfmac-gtk-install-rollback.timer', commands)
        self.assertNotIn('systemctl enable --now', commands)

    def test_confirmation_requires_loaded_candidate(self):
        self.run_mode('install', self.candidate)
        self.run_mode('confirm', success=False)
        self.assertTrue(self.pending.exists())
        self.loaded.write_text(VERSION)
        self.run_mode('confirm')
        self.assertFalse(self.pending.exists())
        self.assertFalse(self.timer.exists())
        self.assertTrue(self.module.exists())

    def test_rollback_restores_stock_and_reboots(self):
        self.run_mode('install', self.candidate)
        self.run_mode('remove', '--reboot')
        self.assertFalse(self.module.exists())
        self.assertFalse(self.pending.exists())
        self.assertIn('systemctl reboot', (self.root / 'commands').read_text())

    def test_failed_boot_image_update_rolls_back_installation(self):
        (self.root / 'fail-update').touch()
        self.run_mode('install', self.candidate, success=False)
        self.assertFalse(self.module.exists())
        self.assertFalse(self.pending.exists())

    def test_rollback_does_not_delete_another_artifact(self):
        self.run_mode('install', self.candidate)
        self.module.write_bytes(b'another artifact')
        self.run_mode('remove', success=False)
        self.assertEqual(self.module.read_bytes(), b'another artifact')
        self.assertTrue(self.pending.exists())


if __name__ == '__main__':
    unittest.main()
