"""Scene-based setup checks and unattended fixes against fake CLIs on PATH."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/prepare.py"
FAKE = ROOT / "tests/fixtures-bin.py"
EXAMPLE = json.loads((ROOT.parents[1] / "config/workbench.example.json").read_text())
FIELDS = list(EXAMPLE["bug_report"]["field_map"].values())


class PrepareTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(sys.executable)  # for the fakes' shebang
        self.data = self.base / "data"
        self.agents = self.base / "LaunchAgents"
        self.agents.mkdir()
        self.tools = {"fields": FIELDS, "push": ["tutti", "tutti-server", "tsh-websocket"]}

    def install(self, *names):
        for name in names:
            shutil.copyfile(FAKE, self.bin / name)
            (self.bin / name).chmod(0o755)

    def prepare(self, operation, *scenes, expected=0):
        env = {"PATH": str(self.bin), "HOME": str(self.base), "FAKE_TOOLS": json.dumps(self.tools),
               "FAKE_TOOLS_LOG": str(self.base / "calls.log"), "LAUNCH_AGENTS_DIR": str(self.agents)}
        arguments = [arg for scene in scenes for arg in ("--scene", scene)]
        result = subprocess.run([sys.executable, str(SCRIPT), operation, *arguments, "--data-dir", str(self.data)],
                                capture_output=True, text=True, timeout=120, env=env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        return report, {entry["id"]: entry for entry in report["items"]}

    def test_investigate_installs_what_it_can_then_reports_whats_left(self):
        self.install("node", "npm", "npx")
        report, items = self.prepare("check", "investigate")
        self.assertEqual(set(report["scenes"]), {"investigate"})
        self.assertEqual((items["config"]["status"], items["lark-cli"]["status"], items["tutti-ops"]["status"]),
                         ("fix", "fix", "fix"))
        self.assertNotIn("codex", items)  # not part of this scene
        self.tools["tutti_token"] = False
        report, items = self.prepare("fix", "investigate")
        self.assertEqual(len(report["fixed"]), 3, report)
        self.assertEqual(items["config"]["status"], "ok")
        config = json.loads((self.data / "config.json").read_text())
        self.assertEqual(config["tutti_ops"]["admin_url"], "https://admin.tutti.sh")
        self.assertEqual((items["lark-auth"]["status"], items["feishu-table"]["status"]), ("ok", "ok"))
        self.assertEqual(items["tutti-ops-auth"]["status"], "user")
        self.assertIn("admin-tokens", items["tutti-ops-auth"]["guide"][0])
        self.assertEqual(items["chrome-devtools"]["status"], "host")
        self.assertFalse(report["ready"])

    def test_defaults_fill_gaps_but_keep_existing_values(self):
        self.data.mkdir()
        (self.data / "config.json").write_text(json.dumps({
            "schema_version": 1, "feishu": {"table_id": "old"}, "solution_schedule": {"interval_seconds": 600},
            "repositories": [{"name": "tutti", "url": "https://example.git", "base_branch": "main"}]}))
        self.install("node", "npm", "lark-cli")
        self.prepare("fix", "investigate")
        config = json.loads((self.data / "config.json").read_text())
        self.assertEqual(config["feishu"], {"table_id": "old"})
        self.assertEqual(config["solution_schedule"]["interval_seconds"], 600)
        self.assertEqual(config["solution_schedule"]["timeout_minutes"], 45)
        self.assertEqual(config["repositories"][0]["url"], "https://example.git")
        self.assertEqual([repo["name"] for repo in config["repositories"]], ["tutti", "tutti-server", "tsh-websocket"])
        self.assertTrue(config["log_sources"][2]["paths"])
        self.assertIn("bug_report", config)
        self.assertTrue((self.data / "config.before-prepare.json").is_file())

    def test_logins_and_permissions_come_back_as_guided_user_steps(self):
        self.install("node", "npm", "npx", "lark-cli", "git", "codex", "mmdc", "gh")
        self.tools.update(lark_logged_in=False, gh_scopes="'repo'", push=["tutti"], git_helper=False)
        _, items = self.prepare("check", "execute")
        self.assertEqual(items["lark-auth"]["status"], "user")
        self.assertTrue(any("auth login" in step for step in items["lark-auth"]["guide"]))
        self.assertEqual(items["gh-auth"]["status"], "user")
        self.assertIn("workflow", items["gh-auth"]["detail"])
        self.tools.update(lark_logged_in=True, gh_scopes="'repo', 'workflow'")
        report, items = self.prepare("check", "execute")
        self.assertEqual(items["gh-git"]["status"], "fix")
        self.assertEqual(items["deploy-permission"]["status"], "user")
        self.assertIn("tutti-lab/tutti-server", items["deploy-permission"]["detail"])
        self.assertEqual(items["execute-schedule"]["status"], "optional")
        self.assertNotIn("mmdc", items)

    def test_all_scenes_ready_with_schedules(self):
        self.install("node", "npm", "npx", "lark-cli", "git", "codex", "mmdc", "gh", "tutti-ops")
        self.tools.update(gh_scopes="'repo', 'workflow'")
        for name in ("com.tutti.bug-solution.ou_me.plist", "com.tutti.bug-execute.ou_me.plist"):
            (self.agents / name).write_text("<plist/>")
        report, items = self.prepare("fix", "all")
        self.assertEqual(set(report["scenes"]), {"investigate", "solution", "execute"})
        self.assertEqual(items["mmdc"]["status"], "ok")
        self.assertEqual(items["solution-schedule"]["status"], "ok")
        self.assertEqual(report["summary"]["user"], 0, report)
        self.assertEqual(report["summary"]["fix"], 0, report)
        self.assertTrue(report["ready"])


if __name__ == "__main__":
    unittest.main()
