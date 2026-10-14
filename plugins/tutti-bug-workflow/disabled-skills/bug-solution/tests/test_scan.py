"""A scheduled round: lock, code sync, scan, one fake Codex session per pending bug."""

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


def git(directory, *arguments):
    return subprocess.run(["git", "-C", str(directory), *arguments], capture_output=True, text=True,
                          check=True).stdout.strip()


class ScanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        remote = self.base / "remote.git"
        git(self.base, "init", "--bare", "-b", "main", str(remote))
        work = self.base / "work"
        git(self.base, "clone", "-q", str(remote), str(work))
        git(work, "config", "user.email", "t@example.com")
        git(work, "config", "user.name", "t")
        (work / "a.txt").write_text("a")
        git(work, "add", ".")
        git(work, "commit", "-qm", "a")
        git(work, "push", "-q", "origin", "HEAD:main")
        self.main = git(work, "rev-parse", "HEAD")
        self.data = self.base / "data"
        self.data.mkdir()
        cfg = json.loads(EXAMPLE_CONFIG.read_text())
        cfg["repositories"] = [{"name": "tutti", "url": str(remote), "base_branch": "main"}]
        cfg["solution_schedule"]["codex_command"] = str(ROOT / "tests/fixtures-codex.py")
        (self.data / "config.json").write_text(json.dumps(cfg))
        self.state = self.base / "lark.json"
        self.codex_log = self.base / "codex.json"
        records = {
            "rec1": self.bug("P0", "授权弹窗不刷新", [{"file_token": "t1", "name": "shot.png", "size": 4},
                                                {"file_token": "t2", "name": "web-logs.log", "size": 9}]),
            "rec2": self.bug("P1", "任务状态不更新", plan="已驳回"),
            "rec3": self.bug("P3", "文案错别字"),
            "rec4": self.bug("P0", "已在评审", plan="待评审"),
        }
        self.state.write_text(json.dumps({"records": records, "next": 10, "calls": []}))
        self.env = {**os.environ, "LARK_CLI": str(ROOT / "tests/fixtures-lark-cli.py"),
                    "FAKE_LARK_STATE": str(self.state), "FAKE_LARK_USERS": json.dumps(USERS),
                    "FAKE_CODEX_LOG": str(self.codex_log), "FAKE_CODEX_ANALYSE": "rec1",
                    "FAKE_PLAN_FIELD": FIELDS["plan_status"]}

    @staticmethod
    def bug(priority, title, attachments=None, plan=None):
        return {FIELDS["title"]: title, FIELDS["priority"]: [priority], FIELDS["status"]: ["未解决"],
                FIELDS["plan_status"]: plan,
                FIELDS["assignee"]: [{"id": "ou_me", "name": "韦超"}], FIELDS["attachments"]: attachments or [],
                FIELDS["record_time"]: "2026-10-10T00:00:00.000+08:00"}

    def scan(self, *arguments):
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data), "--assignee", "ou_me",
                                 *arguments], capture_output=True, text=True, timeout=120, env=self.env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_each_pending_bug_gets_its_own_session_with_context(self):
        report = self.scan("--min-priority", "P1")
        self.assertEqual(report["pending"], 2)
        self.assertEqual({r["record_id"]: r["status"] for r in report["results"]},
                         {"rec1": "analysed", "rec2": "failed"})
        calls = json.loads(self.codex_log.read_text())
        self.assertEqual(len(calls), 2)
        first = calls[0]
        run_dir = Path(report["results"][0]["run_dir"])
        self.assertEqual(Path(first["cwd"]).resolve(), run_dir.resolve())
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", first["argv"])
        self.assertEqual(first["argv"][first["argv"].index("-i") + 1], str(run_dir / "attachments/shot.png"))
        self.assertIn("record_id：rec1", first["prompt"])
        self.assertIn("驳回意见", calls[1]["prompt"])
        self.assertIn("授权弹窗不刷新", (run_dir / "context.md").read_text())
        self.assertTrue((run_dir / "attachments/web-logs.log").is_file())
        code = json.loads((run_dir / "code.json").read_text())["repositories"][0]
        self.assertEqual((code["sha"], Path(code["checkout"])), (self.main, self.data / "repositories/tutti"))
        self.assertTrue((run_dir / "session.log").read_text().strip().endswith("done"))
        again = self.scan("--min-priority", "P1")  # rec1 is done; rec2 is retried
        self.assertEqual([r["record_id"] for r in again["results"]], ["rec2"])

    def test_dry_run_prepares_without_codex_and_a_running_round_is_skipped(self):
        report = self.scan("--dry-run")
        self.assertEqual(report["summary"]["prepared"], 3)
        self.assertFalse(self.codex_log.exists())
        lock = self.data / "solution-runs/.scan-ou_me.lock"
        with lock.open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.assertEqual(self.scan()["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
