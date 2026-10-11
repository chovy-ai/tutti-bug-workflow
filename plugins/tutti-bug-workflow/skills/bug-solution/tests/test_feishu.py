"""Root cause, solution, acceptance and RD approval against a fake lark-cli."""

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
USERS = [{"open_id": "ou_me", "localized_name": "韦超"},
         {"open_id": "ou_z1", "localized_name": "张三"},
         {"open_id": "ou_z2", "localized_name": "张三丰"},
         {"open_id": "ou_l1", "localized_name": "李四"},
         {"open_id": "ou_l2", "localized_name": "李四"}]


class SolutionFeishuTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.data.mkdir()
        shutil.copyfile(EXAMPLE_CONFIG, self.data / "config.json")
        self.state = self.base / "lark.json"
        self.state.write_text(json.dumps({"records": {"rec1": {FIELDS["title"]: "房间：名称不一致"}},
                                          "next": 2, "calls": []}))
        self.env = {**os.environ, "LARK_CLI": str(FAKE), "FAKE_LARK_STATE": str(self.state),
                    "FAKE_LARK_USERS": json.dumps(USERS)}

    def feishu(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(FEISHU), arguments[0], "--data-dir", str(self.data),
                                 "--record-id", "rec1", *arguments[1:]], capture_output=True, text=True,
                                timeout=30, env=self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def cell(self, key):
        return json.loads(self.state.read_text())["records"]["rec1"].get(FIELDS[key])

    def write_all(self):
        plan = self.base / "plan.md"
        plan.write_text("根本方案：切换房间时同步顶部名称。\n")
        return self.feishu("write", "--set", "root_cause=切换房间未刷新标题状态",
                           "--set", f"solution=@{plan}", "--set", "acceptance=切换三次房间，顶部名称始终一致")

    def test_write_then_approve_appends_block_with_digest(self):
        self.assertEqual(self.write_all()["written"], ["acceptance", "root_cause", "solution"])
        approved = self.feishu("approve", "--approver", "张三", "--quote", "可以，按根本方案修",
                               "--source", "当前对话")
        self.assertEqual((approved["status"], approved["approver"]["open_id"]), ("approved", "ou_z1"))
        solution = self.cell("solution")
        self.assertTrue(solution.startswith("根本方案：切换房间时同步顶部名称。\n\n【RD 批准】\n批准人：张三（ou_z1）"))
        self.assertIn("原话：可以，按根本方案修", solution)
        self.assertRegex(solution, r"摘要：sha256:[0-9a-f]{64}$")

    def test_unchanged_rewrite_keeps_approval_and_any_change_clears_it(self):
        self.write_all()
        self.feishu("approve", "--approver", "张三", "--quote", "同意")
        kept = self.feishu("write", "--set", "solution=根本方案：切换房间时同步顶部名称。")
        self.assertFalse(kept["approval_cleared"])
        self.assertIn("【RD 批准】", self.cell("solution"))
        cleared = self.feishu("write", "--set", "acceptance=切换五次房间")
        self.assertTrue(cleared["approval_cleared"])
        self.assertEqual(self.cell("solution"), "根本方案：切换房间时同步顶部名称。")

    def test_approval_needs_all_three_fields_and_a_unique_approver(self):
        self.assertIn("分析根因", self.feishu("approve", "--approver", "张三", "--quote", "ok", expected=2)["error"])
        self.write_all()
        ambiguous = self.feishu("approve", "--approver", "李四", "--quote", "ok", expected=1)
        self.assertEqual((ambiguous["status"], len(ambiguous["candidates"])), ("ambiguous", 2))
        self.assertNotIn("【RD 批准】", self.cell("solution"))

    def test_approval_block_and_other_fields_cannot_be_written_directly(self):
        forged = self.feishu("write", "--set", "solution=方案\n\n【RD 批准】\n批准人：我", expected=2)
        self.assertIn("approve", forged["error"])
        self.assertIn("cannot be written", self.feishu("write", "--set", "status=已修复", expected=2)["error"])

    def test_download_all_attachments(self):
        state = json.loads(self.state.read_text())
        state["records"]["rec1"][FIELDS["attachments"]] = [
            {"file_token": "t1", "name": "web-logs.log", "size": 5},
            {"file_token": "t2", "name": "server-logs.json", "size": 7}]
        self.state.write_text(json.dumps(state))
        result = self.feishu("download", "--output-dir", str(self.base / "out"))
        self.assertEqual(sorted(item["name"] for item in result["downloaded"]), ["server-logs.json", "web-logs.log"])
        self.assertEqual((self.base / "out/server-logs.json").stat().st_size, 7)


if __name__ == "__main__":
    unittest.main()
