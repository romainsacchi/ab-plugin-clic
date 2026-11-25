import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class InventoryTests(unittest.TestCase):
    def test_brightway_import_in_isolated_project(self):
        script = Path(__file__).with_name("inventory_roundtrip.py")
        with TemporaryDirectory() as data:
            result = subprocess.run(
                [sys.executable, str(script)],
                env={**os.environ, "BRIGHTWAY2_DIR": data},
                capture_output=True,
                text=True,
                timeout=90,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
