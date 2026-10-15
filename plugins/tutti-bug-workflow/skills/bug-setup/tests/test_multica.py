"""Multica status and sync against a stateful fake `multica` on PATH."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/multica.py"
FAKE = ROOT / "tests/fixtures-multica.py"
WORKSPACE = "49e1cbe1-3b0f-47c3-a885-fa372a410183"
CODEX = "1ba9d14a-17ed-4aa1-9e95-c5c4d6449bb0"


def agent(identifier, name, skills=(), runtime=CODEX):
    return {"id": identifier, "name": name, "runtime_id": runtime, "instructions": "旧指令",
            "skills": [{"id": f"s-{skill}", "name": skill, "enabled": True} for skill in skills]}


class MulticaTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        (self.base / "bin").mkdir()
        (self.base / "bin/python3").symlink_to(sys.executable)
        shutil.copyfile(FAKE, self.base / "bin/multica")
        (self.base / "bin/multica").chmod(0o755)
        self.state = self.base / "state.json"
        self.write({
            "workspaces": [{"id": WORKSPACE, "name": "Tutti"}],
            "projects": [{"id": "p1", "title": "Bug列表"}],
            "runtimes": [{"id": CODEX, "name": "Codex (mac)", "status": "online"}],
            "agents": [agent("a1", "噜噜Bug守门员", ["bug-investigate"]), agent("a2", "噜妹Bug分析师", ["bug-solution"]),
                       agent("a3", "牛牛Bug解决专员", ["bug-execute"])],
            "skills": [
                {"id": "s-bug-investigate", "name": "bug-investigate", "content": "old", "description": "old",
                 "files": [{"id": "f1", "path": "scripts/feishu.py", "content": "old"}]},
                {"id": "s-bug-execute", "name": "bug-execute", "content": "old", "description": "old", "files": []},
                {"id": "s-bug-solution", "name": "bug-solution", "content": "old", "description": "old", "files": []},
            ],
        })

    def write(self, value):
        self.state.write_text(json.dumps(value, ensure_ascii=False))

    def read(self):
        return json.loads(self.state.read_text())

    def multica(self, operation, *extra, expected=None):
        env = {"PATH": str(self.base / "bin"), "HOME": str(self.base), "FAKE_MULTICA_STATE": str(self.state),
               "MULTICA_TOKEN": "inherited-from-a-daemon-task"}
        result = subprocess.run([sys.executable, str(SCRIPT), operation, *extra, "--data-dir", str(self.base / "data")],
                                capture_output=True, text=True, timeout=120, env=env, check=False)
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_status_reports_drift_wrong_assignments_and_legacy_skills(self):
        report = self.multica("status", expected=1)
        self.assertEqual(report["workspace_id"], WORKSPACE)  # the only workspace is picked
        self.assertEqual(report["project"]["id"], "p1")
        self.assertEqual(report["skills"]["bug-analyze"], "missing")
        self.assertIn("scripts/feishu.py", report["skills"]["bug-investigate"]["stale"])
        self.assertEqual(report["agents"]["analyze"]["assigned"], ["bug-solution"])
        self.assertEqual(report["legacy_skills"], ["bug-solution"])
        self.assertTrue(any("bug-analyze" in problem for problem in report["problems"]))
        self.assertEqual(self.read()["agents"][0]["instructions"], "旧指令")  # status never writes

    def test_sync_makes_the_workspace_match_the_plugin_source(self):
        report = self.multica("sync", "--prune", expected=0)
        self.assertEqual(report["problems"], [])
        state = self.read()
        skills = {entry["name"]: entry for entry in state["skills"]}
        self.assertNotIn("bug-solution", skills)  # legacy skill pruned once no agent uses it
        source = (ROOT.parent / "bug-analyze/SKILL.md").read_text()
        self.assertEqual(skills["bug-analyze"]["content"], source)
        paths = {f["path"] for f in skills["bug-investigate"]["files"]}
        self.assertNotIn("scripts/feishu.py", paths)
        self.assertIn("references/issue-fields.md", paths)
        self.assertFalse(any(path.startswith("tests/") for path in paths))
        assigned = {entry["name"]: [s["name"] for s in entry["skills"]] for entry in state["agents"]}
        self.assertEqual(assigned, {"噜噜Bug守门员": ["bug-investigate"], "噜妹Bug分析师": ["bug-analyze"],
                                    "牛牛Bug解决专员": ["bug-execute"]})
        investigator = state["agents"][0]["instructions"]
        self.assertIn("噜妹Bug分析师", investigator)  # the hand-off target comes from the config
        # The profile is always explicit: a daemon task's MULTICA_* environment must not leak in.
        self.assertTrue(all(call[:2] == ["--profile", "desktop-api.multica.ai"] for call in state["calls"]))
        writes = len(state["calls"])
        self.multica("sync", expected=0)
        rewrites = [call for call in self.read()["calls"][writes:] if "upsert" in call or "delete" in call]
        self.assertEqual(rewrites, [])  # a second sync only rewrites what changed

    def test_missing_agents_and_offline_runtime_are_reported_not_created(self):
        state = self.read()
        state["agents"] = state["agents"][:2]
        state["runtimes"][0]["status"] = "offline"
        self.write(state)
        report = self.multica("status", expected=1)
        self.assertIn("不存在", report["agents"]["execute"]["problem"])
        self.assertIn("runtime 不在线", report["agents"]["investigate"]["problem"])
        self.assertIn("牛牛Bug解决专员", self.multica("sync", expected=2)["error"])
        self.assertEqual(len(self.read()["agents"]), 2)

    def test_several_workspaces_need_an_explicit_choice(self):
        state = self.read()
        state["workspaces"].append({"id": "59e1cbe1-3b0f-47c3-a885-fa372a410183", "name": "Other"})
        self.write(state)
        self.assertIn("multica.workspace_id", self.multica("status", expected=2)["error"])
        (self.base / "data").mkdir()
        (self.base / "data/config.json").write_text(json.dumps({"multica": {"workspace_id": WORKSPACE}}))
        self.assertEqual(self.multica("status", expected=1)["workspace_id"], WORKSPACE)

    def test_an_old_cli_that_only_prints_a_workspace_table_still_works(self):
        state = self.read()
        state["cli"] = "legacy"
        self.write(state)
        self.assertEqual(self.multica("status", expected=1)["workspace_id"], WORKSPACE)

    def test_logged_out_profile_is_an_error(self):
        state = self.read()
        state["logged_in"] = False
        self.write(state)
        self.assertIn("未登录", self.multica("status", expected=2)["error"])


if __name__ == "__main__":
    unittest.main()
