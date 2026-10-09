"""Stateless feishu.py against a fake lark-cli; no network or real Base."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "scripts/workbench.py"
FEISHU = ROOT / "scripts/feishu.py"
FAKE = ROOT / "tests/fixtures-lark-cli.py"


class FeishuTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.state = self.base / "lark.json"
        self.env = {**os.environ, "LARK_CLI": str(FAKE), "FAKE_LARK_STATE": str(self.state)}
        self.run_script(WORKBENCH, "init")
        self.fields = json.loads((self.data / "config.json").read_text())["feishu"]["field_map"]

    def run_script(self, script, operation, *arguments, expected=0, env=None):
        result = subprocess.run([sys.executable, str(script), operation, "--data-dir", str(self.data),
                                 *arguments], capture_output=True, text=True, timeout=30,
                                env=env or self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def feishu(self, *arguments, expected=0, env=None):
        return self.run_script(FEISHU, *arguments, expected=expected, env=env)

    def lark(self):
        return json.loads(self.state.read_text())

    def record(self):
        return self.lark()["records"]["rec1"]

    def test_create_sets_bug_stage_and_reuses_record_with_same_title(self):
        created = self.feishu("create", "--title", "Popover misplaced", "--description", "Steps...")
        self.assertEqual(created, {"action": "created", "record_id": "rec1"})
        self.assertEqual(self.record()[self.fields["workflow_status"]], "bug单")
        again = self.feishu("create", "--title", "Popover misplaced", "--description", "Steps...")
        self.assertEqual(again, {"action": "existing", "record_id": "rec1"})
        self.assertEqual(len(self.lark()["records"]), 1)

    def test_interrupted_create_is_found_again_instead_of_duplicated(self):
        crash = {**self.env, "FAKE_LARK_CRASH_AFTER_CREATE": "1"}
        self.feishu("create", "--title", "Popover misplaced", "--description", "x", expected=2, env=crash)
        recovered = self.feishu("create", "--title", "Popover misplaced", "--description", "x")
        self.assertEqual(recovered, {"action": "existing", "record_id": "rec1"})
        self.assertEqual(len(self.lark()["records"]), 1)

    def test_write_overwrites_owned_fields_and_appends_without_duplicating(self):
        self.feishu("create", "--title", "T", "--description", "D")
        state = self.lark()
        state["records"]["rec1"][self.fields["dialogue"]] = "QA: human note"
        self.state.write_text(json.dumps(state))
        note = self.base / "conclusion.md"
        note.write_text("Root cause confirmed")
        result = self.feishu("write", "--record-id", "rec1", "--set", f"analysis_conclusion=@{note}",
                             "--append", "dialogue=Agent: asked for device")
        self.assertEqual(result["written"], ["analysis_conclusion", "dialogue"])
        retry = self.feishu("write", "--record-id", "rec1", "--append", "dialogue=Agent: asked for device")
        self.assertEqual(retry["already_present"], ["dialogue"])
        self.assertEqual(self.record()[self.fields["analysis_conclusion"]], "Root cause confirmed")
        self.assertEqual(self.record()[self.fields["dialogue"]], "QA: human note\n\nAgent: asked for device")
        self.feishu("write", "--record-id", "rec1", "--set", "acceptance_report=x", expected=2)
        self.feishu("write", "--record-id", "rec1", "--set", "dialogue=x", expected=2)

    def test_attach_verifies_read_back_and_skips_files_already_on_the_record(self):
        self.feishu("create", "--title", "T", "--description", "D")
        log = self.base / "web-logs.log"
        log.write_text('{"type":"metadata"}\n')
        first = self.feishu("attach", "--record-id", "rec1", "--file", str(log))
        self.assertEqual([item["name"] for item in first["uploaded"]], ["web-logs.log"])
        second = self.feishu("attach", "--record-id", "rec1", "--file", str(log))
        self.assertEqual(second["uploaded"], [])
        self.assertEqual(second["already_attached"][0]["file_token"], first["uploaded"][0]["file_token"])
        self.assertEqual(self.lark()["calls"].count("+record-upload-attachment"), 1)
        log.write_text('{"type":"metadata","more":true}\n')
        third = self.feishu("attach", "--record-id", "rec1", "--file", str(log))
        self.assertEqual(len(third["uploaded"]), 1)

    def test_cli_failures_are_explicit(self):
        failing = {**self.env, "FAKE_LARK_FAIL": "+record-upsert"}
        error = self.feishu("create", "--title", "T", "--description", "D", expected=2, env=failing)
        self.assertIn("simulated failure", error["error"])
        self.feishu("write", "--record-id", "rec1", expected=2)


if __name__ == "__main__":
    unittest.main()
