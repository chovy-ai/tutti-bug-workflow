"""Stateless feishu.py against a fake lark-cli and the example bug_report table."""

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
USERS = [{"open_id": "ou_me", "localized_name": "韦超", "has_chatted": True},
         {"open_id": "ou_z1", "localized_name": "张三", "department": "Web", "has_chatted": True},
         {"open_id": "ou_z2", "localized_name": "张三丰", "department": "Server"},
         {"open_id": "ou_l1", "localized_name": "李四", "department": "QA"},
         {"open_id": "ou_l2", "localized_name": "李四", "department": "Ops"}]


class FeishuTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.data.mkdir()
        shutil.copyfile(EXAMPLE_CONFIG, self.data / "config.json")
        self.state = self.base / "lark.json"
        self.env = {**os.environ, "LARK_CLI": str(FAKE), "FAKE_LARK_STATE": str(self.state),
                    "FAKE_LARK_USERS": json.dumps(USERS)}

    def feishu(self, *arguments, expected=0, env=None):
        result = subprocess.run([sys.executable, str(FEISHU), arguments[0], "--data-dir", str(self.data),
                                 *arguments[1:]], capture_output=True, text=True, timeout=30,
                                env=env or self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def lark(self):
        return json.loads(self.state.read_text())

    def record(self):
        return {key: self.lark()["records"]["rec1"].get(field) for key, field in FIELDS.items()}

    def test_create_fills_defaults_reporter_time_and_view_fields(self):
        created = self.feishu("create", "--title", "房间：顶部名称与左侧不一致", "--record-time", "2026-10-10T09:30:00Z",
                              "--set", "platform=新框架一期-Web", "--set", "priority=P1", "--set", "module=房间/群聊")
        self.assertEqual((created["action"], created["record_id"]), ("created", "rec1"))
        record = self.record()
        self.assertEqual((record["status"], record["issue_type"], record["reporter"]), ("未解决", "bug", [{"id": "ou_me"}]))
        self.assertEqual(record["record_time"], "2026-10-10 17:30:00")  # Asia/Shanghai
        self.assertEqual((record["platform"], record["priority"], record["module"]), ("新框架一期-Web", "P1", "房间/群聊"))
        again = self.feishu("create", "--title", "房间：顶部名称与左侧不一致")
        self.assertEqual(again, {"action": "existing", "record_id": "rec1"})
        self.assertEqual(len(self.lark()["records"]), 1)

    def test_interrupted_create_is_found_again_instead_of_duplicated(self):
        crash = {**self.env, "FAKE_LARK_CRASH_AFTER_CREATE": "1"}
        self.feishu("create", "--title", "T", expected=2, env=crash)
        self.assertEqual(self.feishu("create", "--title", "T"), {"action": "existing", "record_id": "rec1"})

    def test_select_values_are_validated_and_p2_is_flagged(self):
        self.feishu("create", "--title", "T")
        self.feishu("write", "--record-id", "rec1", "--set", "module=不存在的模块", expected=2)
        self.feishu("write", "--record-id", "rec1", "--set", "platform=个人版-桌面端", expected=2)
        result = self.feishu("write", "--record-id", "rec1", "--set", "priority=P2")
        self.assertTrue(any("vewoD2kiPo" in note for note in result["notes"]))
        self.feishu("write", "--record-id", "rec1", "--set", "status=已关闭", expected=2)
        self.assertEqual(self.feishu("options", "--field", "platform")["options"],
                         ["新框架一期-Mac", "新框架一期-Windows", "新框架一期-Web"])

    def test_context_fields_are_written_and_root_cause_is_not_settable(self):
        self.feishu("create", "--title", "T", "--set", "page_url=https://tutti.sh/platform/rooms/r1",
                    "--set", "env_version=环境：生产（tutti.sh）\nWeb：abc123", "--set", "context=期望：一致\n实际：不一致")
        record = self.record()
        self.assertEqual(record["page_url"], "https://tutti.sh/platform/rooms/r1")
        self.assertIn("生产", record["env_version"])
        self.assertIn("实际", record["context"])
        self.feishu("write", "--record-id", "rec1", "--set", "root_cause=x", expected=2)

    def test_attach_verifies_read_back_and_skips_files_already_on_the_record(self):
        self.feishu("create", "--title", "T")
        shot = self.base / "screenshot.png"
        shot.write_bytes(b"png")
        log = self.base / "tutti-web-diagnostics.zip"
        log.write_bytes(b"zip")
        first = self.feishu("attach", "--record-id", "rec1", "--file", str(shot), "--file", str(log))
        self.assertEqual({item["name"] for item in first["uploaded"]}, {"screenshot.png", "tutti-web-diagnostics.zip"})
        second = self.feishu("attach", "--record-id", "rec1", "--file", str(shot))
        self.assertEqual((second["uploaded"], len(second["already_attached"])), ([], 1))
        self.assertEqual(self.lark()["calls"].count("+record-upload-attachment"), 1)

    def test_download_fetches_attachment_already_on_the_record(self):
        self.feishu("create", "--title", "T")
        archive = self.base / "tutti-web-diagnostics.zip"
        archive.write_bytes(b"zipdata")
        self.feishu("attach", "--record-id", "rec1", "--file", str(archive))
        result = self.feishu("download", "--record-id", "rec1", "--name", archive.name,
                             "--output-dir", str(self.base / "dl"))
        self.assertEqual(result["size"], len(b"zipdata"))

    def test_assignee_resolves_or_reports_without_writing(self):
        self.feishu("create", "--title", "T")
        self.assertEqual(self.feishu("assign", "--record-id", "rec1", "--name", "张三")["status"], "assigned")
        self.assertEqual(self.record()["assignee"], [{"id": "ou_z1"}])
        ambiguous = self.feishu("assign", "--record-id", "rec1", "--name", "李四")
        self.assertEqual({c["department"] for c in ambiguous["candidates"]}, {"QA", "Ops"})
        self.assertEqual(self.feishu("assign", "--record-id", "rec1")["status"], "missing")
        self.assertEqual(self.feishu("assign", "--record-id", "rec1", "--name", "王五")["status"], "not_found")
        self.assertEqual(self.record()["assignee"], [{"id": "ou_z1"}])

    def test_cli_failures_are_explicit(self):
        failing = {**self.env, "FAKE_LARK_FAIL": "+record-upsert"}
        self.assertIn("simulated failure", self.feishu("create", "--title", "T", expected=2, env=failing)["error"])
        self.feishu("write", "--record-id", "rec1", expected=2)


if __name__ == "__main__":
    unittest.main()
