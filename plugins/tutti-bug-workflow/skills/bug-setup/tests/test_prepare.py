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
FAKE_MULTICA = ROOT / "tests/fixtures-multica.py"
WORKSPACE = "49e1cbe1-3b0f-47c3-a885-fa372a410183"
EXAMPLE = json.loads((ROOT.parents[1] / "config/workbench.example.json").read_text())


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
        self.tools = {"push": ["tutti", "tutti-server", "tsh-websocket"]}
        shutil.copyfile(FAKE_MULTICA, self.bin / "multica")
        (self.bin / "multica").chmod(0o755)
        self.multica = self.base / "multica.json"
        self.multica.write_text(json.dumps({
            "workspaces": [{"id": WORKSPACE, "name": "Tutti"}], "projects": [{"id": "p1", "title": "Bug列表"}],
            "runtimes": [{"id": "r1", "name": "Codex (mac)", "status": "online"}],
            "agents": [{"id": f"a{i}", "name": name, "runtime_id": "r1", "instructions": "", "skills": []}
                       for i, name in enumerate(("噜噜Bug守门员", "噜妹Bug分析师", "牛牛Bug解决专员"))],
            "skills": []}, ensure_ascii=False))

    def install(self, *names):
        for name in names:
            shutil.copyfile(FAKE, self.bin / name)
            (self.bin / name).chmod(0o755)

    def prepare(self, operation, *scenes, expected=0):
        env = {"PATH": str(self.bin), "HOME": str(self.base), "FAKE_TOOLS": json.dumps(self.tools),
               "FAKE_TOOLS_LOG": str(self.base / "calls.log"), "LAUNCH_AGENTS_DIR": str(self.agents),
               "FAKE_MULTICA_STATE": str(self.multica)}
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
        self.assertEqual((items["config"]["status"], items["tutti-ops"]["status"]), ("fix", "fix"))
        self.assertEqual((items["multica-skills"]["status"], items["multica-skills"]["fix"]), ("fix", "multica-sync"))
        self.assertNotIn("codex", items)  # not part of this scene
        self.assertNotIn("gh-auth", items)  # pushing and deploying belong to the execute scene
        self.tools["tutti_token"] = False
        report, items = self.prepare("fix", "investigate")
        self.assertEqual(len(report["fixed"]), 3, report)  # config, tutti-ops, Multica skills
        self.assertEqual(items["multica-skills"]["status"], "ok")
        self.assertEqual(items["config"]["status"], "ok")
        config = json.loads((self.data / "config.json").read_text())
        self.assertEqual(config["tutti_ops"]["admin_url"], "https://admin.tutti.sh")
        self.assertEqual(items["tutti-ops-auth"]["status"], "user")
        self.assertIn("admin-tokens", items["tutti-ops-auth"]["guide"][0])
        self.assertEqual(items["chrome-devtools"]["status"], "host")
        self.assertFalse(report["ready"])

    def test_multica_login_agents_and_project_are_for_the_person(self):
        self.install("node", "npm", "npx")
        state = json.loads(self.multica.read_text())
        state["logged_in"] = False
        self.multica.write_text(json.dumps(state, ensure_ascii=False))
        _, items = self.prepare("check", "investigate")
        self.assertEqual(items["multica"]["status"], "user")
        self.assertIn("Multica 桌面端", items["multica"]["guide"][0])
        state.update(logged_in=True, projects=[], agents=state["agents"][:2])
        self.multica.write_text(json.dumps(state, ensure_ascii=False))
        _, items = self.prepare("check", "investigate")
        self.assertEqual(items["multica-project"]["status"], "user")
        self.assertEqual(items["multica-agents"]["status"], "user")
        self.assertIn("牛牛Bug解决专员", items["multica-agents"]["detail"])
        self.assertEqual(items["multica-skills"]["status"], "user")  # no sync until every agent exists
        self.assertNotIn("fix", items["multica-skills"])

    def test_defaults_fill_gaps_but_keep_existing_values(self):
        self.data.mkdir()
        (self.data / "config.json").write_text(json.dumps({
            "schema_version": 1, "tutti_ops": {"admin_url": "https://admin.example"},
            "repositories": [{"name": "tutti", "url": "https://example.git", "base_branch": "main"}]}))
        self.install("node", "npm")
        self.prepare("fix", "investigate")
        config = json.loads((self.data / "config.json").read_text())
        self.assertEqual(config["tutti_ops"]["admin_url"], "https://admin.example")
        self.assertEqual(config["deploy"]["branch_prefix"], "codex/bug-")
        self.assertEqual(config["repositories"][0]["url"], "https://example.git")
        self.assertEqual([repo["name"] for repo in config["repositories"]], ["tutti", "tutti-server", "tsh-websocket"])
        self.assertTrue(config["log_sources"][2]["paths"])
        self.assertNotIn("bug_report", config)
        self.assertTrue((self.data / "config.before-prepare.json").is_file())

    def test_execute_guides_github_login_and_deploy_permissions(self):
        self.install("node", "npm", "npx", "git", "gh")
        self.tools.update(gh_scopes="'repo'", push=["tutti"], git_helper=False)
        _, items = self.prepare("check", "execute")
        self.assertEqual(items["gh-auth"]["status"], "user")
        self.assertIn("workflow", items["gh-auth"]["detail"])
        self.assertEqual(items["multica-project"]["status"], "ok")  # fix replies go onto the Multica issue
        self.tools.update(gh_scopes="'repo', 'workflow'")
        _, items = self.prepare("check", "execute")
        self.assertEqual(items["gh-git"]["status"], "fix")
        self.assertEqual(items["deploy-permission"]["status"], "user")
        self.assertIn("tutti-lab/tutti-server", items["deploy-permission"]["detail"])
        self.assertNotIn("tutti-ops-auth", items)  # log recall is only for reporting

    def test_all_scenes_ready_with_multica_as_the_record(self):
        self.install("node", "npm", "npx", "git", "gh", "tutti-ops")
        self.tools.update(gh_scopes="'repo', 'workflow'")
        report, items = self.prepare("fix", "all")
        self.assertEqual(set(report["scenes"]), {"investigate", "analyze", "execute"})
        self.assertNotIn("tutti-cli", items)
        self.assertTrue({"lark-auth", "feishu-table", "codex-login", "mmdc"}.isdisjoint(items))
        self.assertFalse(any(name.endswith("-schedule") for name in items))
        self.assertEqual(report["summary"]["user"], 0, report)
        self.assertEqual(report["summary"]["fix"], 0, report)
        self.assertTrue(report["ready"])
        result = subprocess.run([sys.executable, str(SCRIPT), "check", "--scene", "solution",
                                 "--data-dir", str(self.data)], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)

if __name__ == "__main__":
    unittest.main()
