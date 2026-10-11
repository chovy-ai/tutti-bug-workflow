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

    def test_write_then_hand_over_for_review(self):
        self.assertEqual(self.write_all()["written"], ["acceptance", "root_cause", "solution"])
        self.assertEqual(self.cell("solution"), "根本方案：切换房间时同步顶部名称。")
        handed = self.feishu("set-plan-status", "--value", "待评审")
        self.assertEqual((handed["plan_status"], handed["previous"]), ("待评审", "（空）"))
        self.assertEqual(self.cell("plan_status"), "待评审")

    def test_review_needs_all_three_fields_and_only_review_can_be_set(self):
        self.assertIn("分析根因", self.feishu("set-plan-status", "--value", "待评审", expected=2)["error"])
        self.write_all()
        self.assertIn("RD", self.feishu("set-plan-status", "--value", "已批准", expected=2)["error"])
        self.assertIn("cannot be written", self.feishu("write", "--set", "status=已修复", expected=2)["error"])

    def test_guarded_writes_stop_once_rd_moved_the_plan_on(self):
        for status in ("未处理", "已驳回"):
            self.seed({"rec1": {FIELDS["title"]: "x", FIELDS["plan_status"]: status}})
            self.feishu("write", "--if-open", "--set", "root_cause=新根因")
            self.assertEqual(self.cell("root_cause"), "新根因")
        for status in ("待评审", "已批准"):
            self.seed({"rec1": {FIELDS["title"]: "x", FIELDS["plan_status"]: status, FIELDS["root_cause"]: "旧"}})
            skipped = self.feishu("write", "--if-open", "--set", "root_cause=新根因", expected=3)
            self.assertEqual(skipped["plan_status"], status)
            self.assertEqual(self.cell("root_cause"), "旧")
            self.assertTrue(self.feishu("set-plan-status", "--value", "待评审", expected=3)["skipped"])

    def seed(self, records):
        state = json.loads(self.state.read_text())
        state["records"] = records
        self.state.write_text(json.dumps(state))

    def scan(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(FEISHU), "scan", "--data-dir", str(self.data), *arguments],
                                capture_output=True, text=True, timeout=30, env=self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def bug(self, priority, day, assignee="ou_me", status="未解决", plan=None):
        return {FIELDS["title"]: f"{priority}-{day}", FIELDS["priority"]: [priority] if priority else None,
                FIELDS["status"]: [status], FIELDS["assignee"]: [{"id": assignee, "name": "x"}],
                FIELDS["record_time"]: f"2026-10-{day:02d}T00:00:00.000+08:00", FIELDS["plan_status"]: plan}

    def test_scan_lists_pending_bugs_of_the_assignee_by_priority_then_age(self):
        self.seed({"r1": self.bug("P2", 1, plan="未处理"), "r2": self.bug("P0", 5, plan="已驳回"),
                   "r3": self.bug("P1", 2), "r4": self.bug("P0", 3), "r5": self.bug("P0", 1, plan="待评审"),
                   "r9": self.bug("P0", 1, plan="已批准"),
                   "r6": self.bug("P0", 1, status="已修复"), "r7": self.bug("P0", 1, assignee="ou_z1"),
                   "r8": self.bug(None, 1)})
        found = self.scan()
        self.assertEqual(found["assignee"]["open_id"], "ou_me")
        self.assertEqual(found["records"][1]["plan_status"], "已驳回")
        self.assertEqual([r["record_id"] for r in found["records"]], ["r4", "r2", "r3", "r1", "r8"])
        self.assertEqual([r["record_id"] for r in self.scan("--min-priority", "P1")["records"]], ["r4", "r2", "r3"])
        self.assertEqual([r["record_id"] for r in self.scan("--assignee", "张三")["records"]], ["r7"])
        self.assertEqual(self.scan("--assignee", "李四", expected=1)["status"], "ambiguous")

    def test_scan_reads_every_page(self):
        self.seed({f"r{i:03d}": self.bug("P1", 1 + i % 28) for i in range(205)})
        self.assertEqual(len(self.scan()["records"]), 205)

    def test_context_writes_record_fields_and_downloads_attachments(self):
        self.seed({"rec1": {FIELDS["title"]: "授权：弹窗状态不刷新", FIELDS["context"]: "期望：刷新\n实际：不刷新",
                            FIELDS["env_version"]: "环境：PPE", FIELDS["page_url"]: {"link": "https://ppe.tutti.sh/x"},
                            FIELDS["assignee"]: [{"id": "ou_me", "name": "韦超"}], FIELDS["priority"]: ["P1"],
                            FIELDS["plan_status"]: "已驳回", FIELDS["rejection"]: "没有覆盖多标签页的情况",
                            FIELDS["attachments"]: [{"file_token": "t1", "name": "web-logs.log", "size": 5},
                                                    {"file_token": "t2", "name": "shot.png", "size": 3}]}})
        result = self.feishu("context", "--output-dir", str(self.base / "run"))
        text = (self.base / "run/context.md").read_text()
        for expected in ("## 问题上下文", "实际：不刷新", "环境：PPE", "https://ppe.tutti.sh/x", "韦超", "P1",
                         "attachments/web-logs.log", "## 驳回意见", "没有覆盖多标签页的情况"):
            self.assertIn(expected, text)
        self.assertEqual(len(result["attachments"]), 2)
        self.assertEqual((self.base / "run/attachments/shot.png").stat().st_size, 3)

    def test_diagrams_take_png_only(self):
        png = self.base / "flow-rec1.png"
        png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        self.assertEqual(len(self.feishu("attach", "--file", str(png))["uploaded"]), 1)
        self.assertEqual(self.cell("diagrams")[0]["name"], "flow-rec1.png")
        text = self.base / "flow.mmd"
        text.write_text("flowchart TD")
        self.assertIn("PNG", self.feishu("attach", "--file", str(text), expected=2)["error"])

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
