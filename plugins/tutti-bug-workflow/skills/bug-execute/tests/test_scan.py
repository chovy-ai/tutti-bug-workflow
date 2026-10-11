"""A scheduled fix round: stale-claim recovery, claim, one fake Codex session per approved bug."""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/scan.py"
EXAMPLE_CONFIG = ROOT.parents[1] / "config/workbench.example.json"
FIELDS = json.loads(EXAMPLE_CONFIG.read_text())["bug_report"]["field_map"]
USERS = [{"open_id": "ou_me", "localized_name": "韦超"}]


class ScanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.data = self.base / "data"
        self.data.mkdir()
        cfg = json.loads(EXAMPLE_CONFIG.read_text())
        cfg["execute_schedule"]["codex_command"] = str(ROOT / "tests/fixtures-codex.py")
        (self.data / "config.json").write_text(json.dumps(cfg))
        self.state = self.base / "lark.json"
        self.codex_log = self.base / "codex.json"
        records = {
            "recA1": self.bug("P0", "授权弹窗不刷新", "已批准", [{"file_token": "t1", "name": "shot.png", "size": 4}]),
            "recB2": self.bug("P1", "任务状态不更新", "已批准"),
            "recC3": self.bug("P1", "上轮中断", "修复中"),
            "recD4": self.bug("P0", "还在评审", "待评审"),
        }
        self.state.write_text(json.dumps({"records": records, "next": 10, "calls": []}))
        self.env = {**os.environ, "LARK_CLI": str(ROOT / "tests/fixtures-lark-cli.py"),
                    "FAKE_LARK_STATE": str(self.state), "FAKE_LARK_USERS": json.dumps(USERS),
                    "FAKE_CODEX_LOG": str(self.codex_log), "FAKE_CODEX_ANALYSE": "recA1",
                    "FAKE_PLAN_FIELD": FIELDS["plan_status"], "FAKE_PLAN_VALUE": "已部署待验收"}

    @staticmethod
    def bug(priority, title, plan, attachments=None):
        return {FIELDS["title"]: title, FIELDS["priority"]: [priority], FIELDS["status"]: ["未解决"],
                FIELDS["plan_status"]: plan, FIELDS["assignee"]: [{"id": "ou_me", "name": "韦超"}],
                FIELDS["attachments"]: attachments or [], FIELDS["root_cause"]: "根因", FIELDS["solution"]: "方案",
                FIELDS["acceptance"]: "验收", FIELDS["record_time"]: "2026-10-10T00:00:00.000+08:00"}

    def record(self, record_id):
        return json.loads(self.state.read_text())["records"][record_id]

    def scan(self, *arguments):
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data), "--assignee", "ou_me",
                                 *arguments], capture_output=True, text=True, timeout=120, env=self.env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_round_recovers_stale_claims_and_fixes_each_approved_bug_in_its_own_session(self):
        report = self.scan()
        self.assertEqual(report["interrupted"], ["recC3"])
        self.assertEqual(self.record("recC3")[FIELDS["plan_status"]], "修复失败")
        self.assertIn("中断", self.record("recC3")[FIELDS["fix_progress"]])
        self.assertEqual({r["record_id"]: r["status"] for r in report["results"]},
                         {"recA1": "deployed", "recB2": "failed"})
        calls = json.loads(self.codex_log.read_text())
        self.assertEqual(len(calls), 2)
        first = calls[0]
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", first["argv"])
        self.assertIn("修复分支：codex/bug-reca1", first["prompt"])
        self.assertIn("PPE 泳道：ppe-bug-reca1", first["prompt"])
        run_dir = Path(report["results"][0]["run_dir"])
        self.assertEqual(json.loads((run_dir / "fix.json").read_text()),
                         {"branch": "codex/bug-reca1", "lane": "ppe-bug-reca1"})
        self.assertIn("## 修复方式", (run_dir / "context.md").read_text())
        progress = self.record("recA1")[FIELDS["fix_progress"]]
        self.assertIn("已批准 → 修复中：定时修复开始，分支 codex/bug-reca1，泳道 ppe-bug-reca1", progress)
        # The session for recB2 ended without a verdict, so the round marks it failed.
        self.assertEqual(self.record("recB2")[FIELDS["plan_status"]], "修复失败")
        self.assertIn("没有更新方案状态", self.record("recB2")[FIELDS["fix_progress"]])
        self.assertEqual(self.record("recD4")[FIELDS["plan_status"]], "待评审")
        self.assertEqual(self.scan()["pending"], 0)

    def test_deployed_sides_always_end_up_in_access_environment(self):
        self.env.update({"FAKE_CODEX_DEPLOY": "recA1,recB2", "FAKE_CODEX_ANALYSE": "", "GH": str(ROOT / "tests/fixtures-gh.py"),
                         "FAKE_GH_LOG": str(self.base / "gh.json"), "FAKE_ENVIRONMENT_FIELD": FIELDS["environment"]})
        report = self.scan("--record-id", "recA1")
        # deploy.py took the record from the session environment and wrote 访问环境 itself.
        self.assertEqual(self.record("recA1")[FIELDS["environment"]], "https://tutti.sh/platform/?webBranch=codex/bug-reca1")
        self.assertEqual((report["results"][0]["backfilled"], report["results"][0]["status"]), (False, "failed"))
        # The session wiped the column: the round fills it back from deploys.jsonl, even on 修复失败.
        self.env["FAKE_CODEX_CLEAR_ENVIRONMENT"] = "1"
        report = self.scan("--record-id", "recB2")
        self.assertEqual(self.record("recB2")[FIELDS["environment"]], "https://tutti.sh/platform/?webBranch=codex/bug-recb2")
        self.assertTrue(report["results"][0]["backfilled"])
        self.assertEqual(self.record("recB2")[FIELDS["plan_status"]], "修复失败")
        self.assertIn("定时任务补填访问环境", self.record("recB2")[FIELDS["fix_progress"]])

    def test_dry_run_claims_nothing_and_a_running_round_is_skipped(self):
        report = self.scan("--dry-run")
        self.assertEqual(report["summary"]["prepared"], 2)
        self.assertEqual(self.record("recA1")[FIELDS["plan_status"]], "已批准")
        self.assertEqual(self.record("recC3")[FIELDS["plan_status"]], "修复中")
        self.assertFalse(self.codex_log.exists())
        with (self.data / "execute-runs/.scan-ou_me.lock").open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.assertEqual(self.scan()["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
