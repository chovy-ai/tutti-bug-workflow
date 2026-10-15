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

    def test_fix_names_come_from_the_issue_key(self):
        names = self.deploy("fix-names", "--issue", "TES-123")
        self.assertEqual((names["branch"], names["lane"]), ("codex/bug-tes-123", "ppe-bug-tes-123"))
        self.assertIn("TES-123", self.deploy("fix-names", "--issue", "01a13d13-2641", expected=2)["error"])

    def test_server_then_websocket_then_web_then_computer(self):
        server = self.deploy("server", "--branch", "codex/bug-rec1", "--lane", "ppe-bug-rec1")
        self.assertTrue(server["ok"])
        self.assertEqual(server["url"], "https://github.com/x/actions/runs/1001")
        self.assertTrue(self.deploy("websocket", "--branch", "codex/bug-rec1", "--lane", "ppe-bug-rec1")["ok"])
        web = self.deploy("web", "--branch", "codex/bug-rec1", "--server-lane", "ppe-bug-rec1")
        self.assertEqual(web["preview_url"], "https://tutti.sh/platform/?webBranch=codex/bug-rec1")
        computer = self.deploy("computer", "--branch", "codex/bug-rec1")
        self.assertEqual(computer["canary_version"], "canary-abcdef123456-1004-1")
        server_call, ws_call, web_call, computer_call = self.dispatches()
        self.assertEqual(ws_call[ws_call.index("-R") + 1], "tutti-lab/tsh-websocket")
        self.assertEqual(ws_call[ws_call.index("--ref") + 1], "codex/bug-rec1")
        self.assertIn("lane=ppe-bug-rec1", ws_call)
        self.assertEqual(server_call[server_call.index("-R") + 1], "tutti-lab/tutti-server")
        self.assertEqual(server_call[server_call.index("--ref") + 1], "codex/bug-rec1")
        self.assertIn("lane=ppe-bug-rec1", server_call)
        self.assertIn("connector_authorization_enabled=false", server_call)
        self.assertEqual(web_call[web_call.index("--ref") + 1], "main")
        self.assertIn("branch=codex/bug-rec1", web_call)
        self.assertIn("server_lane=ppe-bug-rec1", web_call)
        self.assertEqual(computer_call[computer_call.index("--ref") + 1], "codex/bug-rec1")

    def test_failed_run_is_reported_and_missing_url_falls_back_to_listing(self):
        failed = self.deploy("server", "--branch", "b", "--lane", "ppe-bug-rec1", expected=1, FAKE_GH_CONCLUSION="failure")
        self.assertEqual((failed["ok"], failed["conclusion"]), (False, "failure"))
        self.assertIn("contract not found", failed["failed_log_tail"][-1])
        ws = self.deploy("websocket", "--branch", "b", "--lane", "ppe-bug-rec1", expected=1, FAKE_GH_CONCLUSION="failure")
        self.assertIn("deploy-websocket-v2-infrastructure.yml", ws["hint"])
        self.assertIn("ppe-", self.deploy("websocket", "--branch", "b", "--lane", "bug-rec1", expected=2)["error"])
        found = self.deploy("computer", "--branch", "b", FAKE_GH_NO_URL="1")
        self.assertEqual(found["run_id"], 4242)

    def test_successful_deploys_return_the_link_to_try_the_fix(self):
        web = self.deploy("web", "--branch", "codex/bug-0f3a9c21", "--server-lane", "ppe-bug-0f3a9c21")
        self.assertEqual(web["access_url"], "https://tutti.sh/platform/?webBranch=codex/bug-0f3a9c21")
        computer = self.deploy("computer", "--branch", "codex/bug-0f3a9c21")
        self.assertEqual(computer["access_url"], computer["url"])
        self.assertNotIn("access_url", self.deploy("server", "--branch", "b", "--lane", "ppe-bug-0f3a9c21"))
        failed = self.deploy("web", "--branch", "b", expected=1, FAKE_GH_CONCLUSION="failure")
        self.assertNotIn("access_url", failed)

    def test_destroy_only_touches_per_bug_lanes(self):
        self.assertIn("per-bug", self.deploy("destroy-lane", "--lane", "ppe-a", expected=2)["error"])
        self.assertTrue(self.deploy("destroy-lane", "--lane", "ppe-bug-rec1")["ok"])
        self.deploy("destroy-lane", "--lane", "ppe-bug-rec1", "--service", "websocket")
        server_call, ws_call = self.dispatches()
        self.assertIn("destroy-lane.yml", server_call)
        self.assertEqual(server_call[server_call.index("-R") + 1], "tutti-lab/tutti-server")
        self.assertEqual(ws_call[ws_call.index("-R") + 1], "tutti-lab/tsh-websocket")


if __name__ == "__main__":
    unittest.main()
