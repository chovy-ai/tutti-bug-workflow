"""Scene selection and inventory isolation; never install or access external services."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/tool_setup.py"


class ToolSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.data.mkdir()
        self.config = self.data / "config.json"
        self.config.write_bytes((ROOT / "config/workbench.example.json").read_bytes())
        self.env = dict(os.environ, PATH=str(self.base / "empty-bin"))

    def invoke(self, scene, *args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "--scene", scene,
                                 "--data-dir", str(self.data), *args],
                                capture_output=True, text=True, env=self.env, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_solution_is_not_blocked_by_unrelated_logging_or_validation_tools(self):
        before = self.config.read_bytes()
        report = self.invoke("solution")
        self.assertEqual({t["id"] for t in report["tools"]},
                         {"local-workspace", "feishu", "code", "diagrams"})
        self.assertTrue(all(t["selected"] for t in report["tools"]))
        self.assertTrue(all(t["install_plan"] is None for t in report["tools"]))
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(set(p.name for p in self.data.iterdir()), {"config.json"})

    def test_only_reporting_prepares_session_upload_without_claiming_remote_readiness(self):
        before = self.config.read_bytes()
        for scene in ("investigate", "all"):
            with self.subTest(scene=scene):
                report = self.invoke(scene)
                tool = next(t for t in report["tools"] if t["id"] == "session-upload")
                self.assertEqual(tool["requirement"], "required")
                self.assertTrue(tool["selected"])
                self.assertFalse(tool["commands"][0]["available"])
                self.assertEqual(tool["configuration"]["status"], "not_checked")
                self.assertEqual(tool["authentication"], "not_checked")
                self.assertEqual(tool["business_access"], "not_checked")
                self.assertIn("setup-tutti-ops", tool["install_plan"]["argv"])
                self.assertFalse(tool["install_plan"]["executed"])
        for scene in ("solution", "execute"):
            with self.subTest(scene=scene):
                self.assertNotIn("session-upload", {t["id"] for t in self.invoke(scene)["tools"]})
        self.assertEqual(self.config.read_bytes(), before)
        self.assertEqual(set(p.name for p in self.data.iterdir()), {"config.json"})

    def test_selected_remote_log_plan_does_not_install_or_rewrite_custom_configuration(self):
        cfg = json.loads(self.config.read_text())
        next(d for d in cfg["cli_dependencies"] if d["name"] == "tutti-ops")["command"] = "custom-ops"
        self.config.write_text(json.dumps(cfg))
        before = self.config.read_bytes()
        tools = {t["id"]: t for t in self.invoke("investigate", "--include", "remote-computer")["tools"]}
        self.assertTrue(tools["remote-computer"]["selected"])
        self.assertEqual(tools["remote-computer"]["install_plan"]["status"], "review_custom_configuration")
        self.assertFalse(tools["aws-logs"]["selected"])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.data / "tools").exists())

    def test_install_plan_preserves_explicit_configuration_and_remains_unexecuted(self):
        cfg = self.base / "alternate.json"
        cfg.write_bytes(self.config.read_bytes())
        result = self.invoke("investigate", "--include", "remote-computer", "--config", str(cfg))
        tool = next(t for t in result["tools"] if t["id"] == "remote-computer")
        argv = tool["install_plan"]["argv"]
        self.assertIn("setup-tutti-ops", argv)
        self.assertEqual(Path(argv[argv.index("--config") + 1]), cfg.resolve())
        self.assertEqual(Path(argv[argv.index("--data-dir") + 1]), self.data.resolve())
        self.assertFalse(tool["install_plan"]["executed"])
        self.assertFalse(result["installation_performed"])
        self.assertFalse((self.data / "tools").exists())

    def test_configured_browser_does_not_claim_login_or_business_validation(self):
        cfg = json.loads(self.config.read_text())
        cfg["validation"] = {"url": "http://127.0.0.1:8123/preview", "environment": "synthetic",
                             "revision_source": "synthetic version field", "browser_tool": "synthetic-host-tool"}
        self.config.write_text(json.dumps(cfg))
        tool = next(t for t in self.invoke("execute")["tools"] if t["id"] == "browser-validation")
        self.assertEqual(tool["configuration"]["status"], "configured")
        self.assertEqual(tool["authentication"], "not_checked")
        self.assertEqual(tool["business_access"], "not_checked")

    def test_inapplicable_selection_rejected_without_modification(self):
        before = self.config.read_bytes()
        report = self.invoke("solution", "--include", "aws-logs", expected=2)
        self.assertFalse(report["ok"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_missing_configuration_does_not_initialize_workbench(self):
        self.config.unlink()
        report = self.invoke("all", expected=2)
        self.assertFalse(report["ok"])
        self.assertEqual(list(self.data.iterdir()), [])

    def test_all_profiles_deduplicate_common_tools_and_leave_options_unselected(self):
        report = self.invoke("all")
        ids = [t["id"] for t in report["tools"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertFalse(next(t for t in report["tools"] if t["id"] == "aws-logs")["selected"])
        self.assertTrue(next(t for t in report["tools"] if t["id"] == "browser-validation")["selected"])


if __name__ == "__main__":
    unittest.main()
