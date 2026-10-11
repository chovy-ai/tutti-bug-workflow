"""Approval check, verification and PR write-back against a fake lark-cli."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FEISHU = ROOT / "scripts/feishu.py"
FAKE = ROOT / "tests/fixtures-lark-cli.py"
EXAMPLE_CONFIG = ROOT.parents[1] / "config/workbench.example.json"
FIELDS = json.loads(EXAMPLE_CONFIG.read_text())["bug_report"]["field_map"]
ROOT_CAUSE, PLAN, ACCEPTANCE = "切换房间未刷新标题状态", "根本方案：同步顶部名称。", "切换三次房间名称一致"


def approval(root_cause=ROOT_CAUSE, plan=PLAN, acceptance=ACCEPTANCE):
    digest = hashlib.sha256("\n\x1e\n".join((root_cause, plan, acceptance)).encode()).hexdigest()
    return (f"{plan}\n\n【RD 批准】\n批准人：张三（ou_z1）\n时间：2026-10-10 18:00:00\n"
            f"原话：可以\n来源：当前对话\n摘要：sha256:{digest}")


class ExecuteFeishuTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.data.mkdir()
        shutil.copyfile(EXAMPLE_CONFIG, self.data / "config.json")
        self.state = self.base / "lark.json"
        self.save({FIELDS["root_cause"]: ROOT_CAUSE, FIELDS["solution"]: approval(),
                   FIELDS["acceptance"]: ACCEPTANCE})
        self.env = {**os.environ, "LARK_CLI": str(FAKE), "FAKE_LARK_STATE": str(self.state)}

    def save(self, record):
        self.state.write_text(json.dumps({"records": {"rec1": record}, "next": 2, "calls": []}))

    def feishu(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(FEISHU), arguments[0], "--data-dir", str(self.data),
                                 "--record-id", "rec1", *arguments[1:]], capture_output=True, text=True,
                                timeout=30, env=self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def cell(self, key):
        return json.loads(self.state.read_text())["records"]["rec1"].get(FIELDS[key])

    def test_matching_approval_passes_and_returns_the_approved_content(self):
        state = self.feishu("check-approval")
        self.assertTrue(state["approved"])
        self.assertEqual((state["approver"], state["quote"], state["solution"]), ("张三（ou_z1）", "可以", PLAN))

    def test_edits_after_approval_or_missing_block_fail(self):
        self.save({FIELDS["root_cause"]: ROOT_CAUSE, FIELDS["solution"]: approval(),
                   FIELDS["acceptance"]: "改过的验收"})
        self.assertIn("重新批准", self.feishu("check-approval", expected=1)["problems"][0])
        self.save({FIELDS["root_cause"]: ROOT_CAUSE, FIELDS["solution"]: PLAN, FIELDS["acceptance"]: ACCEPTANCE})
        self.assertFalse(self.feishu("check-approval", expected=1)["approved"])

    def test_writes_only_verification_and_appends_prs_once(self):
        self.feishu("write", "--set", "verification=3/3 用例通过")
        self.assertEqual(self.cell("verification"), "3/3 用例通过")
        self.assertIn("cannot be written", self.feishu("write", "--set", "solution=x", expected=2)["error"])
        url = "https://github.com/tutti-lab/tutti/pull/12"
        self.assertTrue(self.feishu("add-pr", "--url", url)["added"])
        self.assertFalse(self.feishu("add-pr", "--url", url)["added"])
        self.feishu("add-pr", "--url", "https://github.com/tutti-lab/tutti-server/pull/3")
        self.assertEqual(self.cell("pull_requests").splitlines()[0], url)
        self.assertEqual(len(self.cell("pull_requests").splitlines()), 2)
        self.assertEqual(self.cell("solution"), approval())

    def test_attach_skips_files_already_on_the_record(self):
        shot = self.base / "after-fix.png"
        shot.write_bytes(b"png")
        self.assertEqual(len(self.feishu("attach", "--file", str(shot))["uploaded"]), 1)
        again = self.feishu("attach", "--file", str(shot))
        self.assertEqual((again["uploaded"], again["already_attached"]), ([], ["after-fix.png"]))


if __name__ == "__main__":
    unittest.main()
