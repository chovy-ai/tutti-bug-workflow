"""Approval check, fix-stage transitions, progress, scan and write-back against a fake lark-cli."""

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


class ExecuteFeishuTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.data.mkdir()
        shutil.copyfile(EXAMPLE_CONFIG, self.data / "config.json")
        self.state = self.base / "lark.json"
        self.save(self.approved())
        self.env = {**os.environ, "LARK_CLI": str(FAKE), "FAKE_LARK_STATE": str(self.state),
                    "FAKE_LARK_USERS": json.dumps([{"open_id": "ou_me", "localized_name": "韦超"}])}

    @staticmethod
    def approved(**changes):
        record = {FIELDS["root_cause"]: ROOT_CAUSE, FIELDS["solution"]: PLAN, FIELDS["acceptance"]: ACCEPTANCE,
                  FIELDS["plan_status"]: "已批准"}
        record.update({FIELDS[key]: value for key, value in changes.items()})
        return record

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

    def test_approved_plan_passes_and_returns_the_approved_content(self):
        state = self.feishu("check-approval")
        self.assertTrue(state["approved"])
        self.assertEqual((state["plan_status"], state["solution"]), ("已批准", PLAN))

    def test_plan_status_other_than_approved_or_empty_fields_fail(self):
        for status in ("待评审", "已驳回", "已部署待验收", None):
            self.save(self.approved(plan_status=status))
            state = self.feishu("check-approval", expected=1)
            self.assertIn("已批准", state["problems"][0])
        self.save(self.approved(acceptance=""))
        self.assertEqual(self.feishu("check-approval", expected=1)["problems"], ["验收标准为空"])

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
        self.assertEqual(self.cell("solution"), PLAN)

    def test_fix_screenshots_go_to_their_own_column_once(self):
        shot = self.base / "fix-rec1-1-202610101830.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 8)
        self.assertEqual(len(self.feishu("attach", "--file", str(shot))["uploaded"]), 1)
        self.assertEqual(self.cell("fix_screenshots")[0]["name"], shot.name)
        self.assertIsNone(self.cell("attachments"))
        second = self.base / "fix-rec1-1b-202610101831.jpg"
        second.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 8)
        self.assertEqual(len(self.feishu("attach", "--file", str(second))["uploaded"]), 1)
        again = self.feishu("attach", "--file", str(shot))
        self.assertEqual((again["uploaded"], again["already_attached"]), ([], [shot.name]))

    def test_fix_screenshots_must_be_named_images(self):
        badly_named = self.base / "after-fix.png"
        badly_named.write_bytes(b"\x89PNG\r\n\x1a\n")
        self.assertIn("fix-<record_id>", self.feishu("attach", "--file", str(badly_named), expected=2)["error"])
        not_image = self.base / "fix-rec1-2-202610101830.png"
        not_image.write_text("log text")
        self.assertIn("PNG or JPEG", self.feishu("attach", "--file", str(not_image), expected=2)["error"])
        log = self.base / "deploy.log"
        log.write_text("ok")
        self.assertEqual(len(self.feishu("attach", "--field", "attachments", "--file", str(log))["uploaded"]), 1)

    def test_fix_stages_move_only_forward_and_log_progress(self):
        self.assertEqual(self.feishu("set-plan-status", "--value", "修复中")["previous"], "已批准")
        self.assertTrue(self.feishu("set-plan-status", "--value", "修复中", expected=3)["skipped"])
        self.feishu("progress", "--message", "PR https://github.com/tutti-lab/tutti/pull/9")
        self.assertIn("访问环境为空", self.feishu("set-plan-status", "--value", "已部署待验收", expected=2)["error"])
        self.feishu("environment", "--url", "https://tutti.sh/x")
        done = self.feishu("set-plan-status", "--value", "已部署待验收", "--note", "预览 https://tutti.sh/x")
        self.assertEqual(done["plan_status"], "已部署待验收")
        lines = self.cell("fix_progress").splitlines()
        self.assertEqual(len(lines), 3)
        self.assertRegex(lines[0], r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] 方案状态 已批准 → 修复中$")
        self.assertIn("pull/9", lines[1])
        self.assertTrue(lines[2].endswith("修复中 → 已部署待验收：预览 https://tutti.sh/x"))
        self.assertIn("Fixing only sets", self.feishu("set-plan-status", "--value", "待评审", expected=2)["error"])
        self.assertTrue(self.feishu("set-plan-status", "--value", "修复失败", expected=3)["skipped"])

    def test_access_environment_is_one_clickable_link_preferring_the_preview(self):
        run = "https://github.com/tutti-lab/tutti/actions/runs/7"
        self.assertTrue(self.feishu("environment", "--service", "computer", "--url", run)["changed"])
        preview = "https://tutti.sh/platform/?webBranch=b1"
        self.assertEqual(self.feishu("environment", "--url", preview)["environment"], preview)
        # A later canary run does not push the preview out.
        self.assertFalse(self.feishu("environment", "--service", "computer", "--url", run + "8")["changed"])
        self.assertEqual(self.cell("environment"), preview)
        self.assertIn("https", self.feishu("environment", "--url", "前端预览：https://x 说明", expected=2)["error"])
        self.assertEqual(self.feishu("set-plan-status", "--value", "修复失败")["environment"], preview)
        # Feishu reads a URL-style cell back as a markdown link.
        self.save(self.approved(environment=f"[{preview}]({preview})"))
        self.assertFalse(self.feishu("environment", "--service", "computer", "--url", run)["changed"])
        self.assertEqual(self.feishu("environment", "--url", preview)["environment"], preview)

    def test_claim_needs_complete_approved_plan(self):
        self.save(self.approved(acceptance=""))
        self.assertIn("验收标准为空", self.feishu("set-plan-status", "--value", "修复中", expected=2)["error"])

    def test_scan_and_context_for_a_fix_session(self):
        base = {FIELDS["status"]: ["未解决"], FIELDS["assignee"]: [{"id": "ou_me", "name": "韦超"}],
                FIELDS["record_time"]: "2026-10-10T00:00:00.000+08:00"}
        records = {"rec1": {**self.approved(), **base, FIELDS["title"]: "授权弹窗", FIELDS["priority"]: ["P1"],
                            FIELDS["diagrams"]: [{"file_token": "d1", "name": "flow-rec1.png", "size": 6}],
                            FIELDS["attachments"]: [{"file_token": "a1", "name": "web-logs.log", "size": 4}]},
                   "rec2": {**self.approved(plan_status="待评审"), **base, FIELDS["title"]: "待评审"},
                   "rec3": {**self.approved(), **base, FIELDS["title"]: "P3 的", FIELDS["priority"]: ["P3"]}}
        self.state.write_text(json.dumps({"records": records, "next": 9, "calls": []}))
        scan = subprocess.run([sys.executable, str(FEISHU), "scan", "--data-dir", str(self.data), "--min-priority", "P1"],
                              capture_output=True, text=True, env=self.env, timeout=30, check=True)
        self.assertEqual([r["record_id"] for r in json.loads(scan.stdout)["records"]], ["rec1"])
        result = self.feishu("context", "--output-dir", str(self.base / "run"))
        text = (self.base / "run/context.md").read_text()
        for expected in ("## 分析根因", ROOT_CAUSE, "## 验收标准", ACCEPTANCE, "diagrams/flow-rec1.png"):
            self.assertIn(expected, text)
        self.assertEqual((len(result["attachments"]), len(result["diagrams"])), (1, 1))


if __name__ == "__main__":
    unittest.main()
