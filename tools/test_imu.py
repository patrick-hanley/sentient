"""Builds firmware/toy-client/imu_events_test.cpp with the host C++ compiler and runs it (synthetic IMU traces through the
real detector header). Skipped when no compiler is installed."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

FW = Path(__file__).resolve().parent.parent / "firmware" / "toy-client"


class ImuDetectorTests(unittest.TestCase):
    def test_detector_replays_synthetic_motion(self):
        cxx = shutil.which("clang++") or shutil.which("g++")
        if not cxx:
            self.skipTest("no C++ compiler")
        with tempfile.TemporaryDirectory() as d:
            exe = Path(d) / "imu_test"
            build = subprocess.run([cxx, "-std=c++17", "-O1", "-Wall", "-Wextra", str(FW / "imu_events_test.cpp"), "-o", str(exe)],
                                   capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout)
            self.assertIn("ALL OK", run.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
