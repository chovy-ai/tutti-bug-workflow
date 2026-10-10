"""check_collection.py only reports state; uses the fake lark-cli."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = ROOT.parents[1] / "config/workbench.example.json"
FEISHU = ROOT / "scripts/feishu.py"
CHECK = ROOT / "scripts/check_collection.py"
FAKE = ROOT / "tests/fixtures-lark-cli.py"


class CheckCollectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.env = {**os.environ, "LARK_CLI": str(FAKE), "FAKE_LARK_STATE": str(self.base / "lark.json")}
        self.data.mkdir()
        shutil.copyfile(EXAMPLE_CONFIG, self.data / "config.json")
        self.call(FEISHU, "create", "--title", "T", "--description", "D")

    def call(self, script, *arguments, expected=0):
        prefix = [arguments[0]] if script != CHECK else []
        rest = arguments[1:] if script != CHECK else arguments
        result = subprocess.run([sys.executable, str(script), *prefix, "--data-dir", str(self.data), *rest],
                                capture_output=True, text=True, timeout=30, env=self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_reports_status_and_attachment_presence_without_blocking(self):
        web_log = self.base / "tutti-web-diagnostics.zip"
        web_log.write_text("{}\n")
        package = self.base / "logs.tar.gz"
        package.write_bytes(b"pkg")
        self.call(FEISHU, "attach", "--record-id", "rec1", "--file", str(web_log))
        web = {"status": "captured", "files": [str(web_log)]}
        computer = {"status": "captured", "files": [{"path": str(package)}]}
        result = self.call(CHECK, "--record-id", "rec1", "--web", json.dumps(web), "--computer", json.dumps(computer))
        self.assertEqual(result["web"]["status"], "captured")
        self.assertTrue(result["web"]["files"][0]["attached"])
        self.assertEqual(result["computer"]["status"], "captured")
        self.assertFalse(result["computer"]["files"][0]["attached"])

    def test_missing_results_and_plain_states_are_reported_as_is(self):
        pending = self.base / "pending.json"
        pending.write_text(json.dumps({"status": "pending", "reason": "waiting for QA device choice"}))
        result = self.call(CHECK, "--record-id", "rec1", "--computer", f"@{pending}")
        self.assertEqual(result["web"], {"status": "not_attempted"})
        self.assertEqual(result["computer"], {"status": "pending", "files": [],
                                              "reason": "waiting for QA device choice"})
        pending = {"status": "pending", "reason": "no_export"}
        self.assertEqual(self.call(CHECK, "--record-id", "rec1", "--web", json.dumps(pending))["web"],
                         {"status": "pending", "files": [], "reason": "no_export"})


if __name__ == "__main__":
    unittest.main()
