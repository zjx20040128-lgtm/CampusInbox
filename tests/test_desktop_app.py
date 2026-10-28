import os
import struct
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "start-desktop.cmd"
EXE = ROOT / "artifacts" / "desktop" / "CampusInbox-Learning-Assistant.exe"
BUILD = ROOT / "desktop-app" / "build.ps1"


class DesktopAppArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        shutil.copytree(ROOT/'desktop-app',self.root/'desktop-app',ignore=shutil.ignore_patterns('.build'))
        shutil.copy2(LAUNCHER,self.root/LAUNCHER.name)
        self.exe=self.root/'artifacts'/'desktop'/EXE.name

    def test_double_click_launcher_builds_missing_desktop_executable(self):
        self.assertTrue(LAUNCHER.is_file(), "missing start-desktop.cmd")
        self.assertFalse(self.exe.exists())
        environment = dict(os.environ, CI_DESKTOP_LAUNCH_TEST="1")
        result = subprocess.run(
            [str(self.root/LAUNCHER.name)], cwd=self.root, env=environment,
            capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(self.exe.is_file(), "launcher did not build the desktop executable")
        self.assertGreater(self.exe.stat().st_size, 4096)

    def test_built_executable_is_a_windows_gui_program(self):
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.root/'desktop-app'/'build.ps1')],
            cwd=self.root, capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue(self.exe.is_file(), "desktop executable must be built first")
        raw = self.exe.read_bytes()
        self.assertEqual(b"MZ", raw[:2])
        pe_offset = struct.unpack_from("<I", raw, 0x3C)[0]
        self.assertEqual(b"PE\0\0", raw[pe_offset:pe_offset + 4])
        self.assertEqual(0x8664, struct.unpack_from("<H", raw, pe_offset + 4)[0], "PE machine must be x64")
        optional_header = pe_offset + 24
        self.assertEqual(2, struct.unpack_from("<H", raw, optional_header + 68)[0], "PE subsystem must be Windows GUI")


if __name__ == "__main__":
    unittest.main()
