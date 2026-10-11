"""PPE deployment dispatch through a fake gh: server lane, web preview, Computer canary."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy.py"
EXAMPLE_CONFIG = ROOT.parents[1] / "config/workbench.example.json"


class DeployTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.data.mkdir()
        shutil.copyfile(EXAMPLE_CONFIG, self.data / "config.json")
        self.log = self.base / "gh.json"
        self.env = {**os.environ, "GH": str(ROOT / "tests/fixtures-gh.py"), "FAKE_GH_LOG": str(self.log)}

    def deploy(self, *arguments, expected=0, **env):
        result = subprocess.run([sys.executable, str(SCRIPT), arguments[0], "--data-dir", str(self.data),
                                 *arguments[1:]], capture_output=True, text=True, timeout=30,
                                env={**self.env, **env}, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def dispatches(self):
        return [call for call in json.loads(self.log.read_text()) if call[:2] == ["workflow", "run"]]

    def test_lane_name_is_a_valid_lowercase_lane(self):
        self.assertEqual(self.deploy("lane-name", "--record-id", "recvuU4kdHhaRU")["lane"], "bug-recvuu4kdhharu")

    def test_server_then_web_then_computer(self):
        server = self.deploy("server", "--branch", "codex/bug-rec1", "--lane", "bug-rec1")
        self.assertTrue(server["ok"])
        self.assertEqual(server["url"], "https://github.com/x/actions/runs/1001")
        web = self.deploy("web", "--branch", "codex/bug-rec1", "--server-lane", "bug-rec1")
        self.assertEqual(web["preview_url"], "https://tutti.sh/platform/?webBranch=codex/bug-rec1")
        computer = self.deploy("computer", "--branch", "codex/bug-rec1")
        self.assertEqual(computer["canary_version"], "canary-abcdef123456-1003-1")
        server_call, web_call, computer_call = self.dispatches()
        self.assertEqual(server_call[server_call.index("-R") + 1], "tutti-lab/tutti-server")
        self.assertEqual(server_call[server_call.index("--ref") + 1], "codex/bug-rec1")
        self.assertIn("lane=bug-rec1", server_call)
        self.assertIn("connector_authorization_enabled=false", server_call)
        self.assertEqual(web_call[web_call.index("--ref") + 1], "main")
        self.assertIn("branch=codex/bug-rec1", web_call)
        self.assertIn("server_lane=bug-rec1", web_call)
        self.assertEqual(computer_call[computer_call.index("--ref") + 1], "codex/bug-rec1")

    def test_failed_run_is_reported_and_missing_url_falls_back_to_listing(self):
        failed = self.deploy("server", "--branch", "b", "--lane", "bug-rec1", expected=1, FAKE_GH_CONCLUSION="failure")
        self.assertEqual((failed["ok"], failed["conclusion"]), (False, "failure"))
        found = self.deploy("computer", "--branch", "b", FAKE_GH_NO_URL="1")
        self.assertEqual(found["run_id"], 4242)

    def test_destroy_only_touches_per_bug_lanes(self):
        self.assertIn("per-bug", self.deploy("destroy-lane", "--lane", "ppe-a", expected=2)["error"])
        self.assertTrue(self.deploy("destroy-lane", "--lane", "bug-rec1")["ok"])
        self.assertIn("destroy-lane.yml", self.dispatches()[0])


if __name__ == "__main__":
    unittest.main()
