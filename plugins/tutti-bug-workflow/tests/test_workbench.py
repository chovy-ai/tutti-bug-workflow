"""Observable local workflow checks; use synthetic data and no external services."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/workbench.py"


class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.data = self.base / "data"
        self.run_cli("init")

    def run_cli(self, operation, *arguments, expected=0, env=None):
        command = [sys.executable, str(SCRIPT), operation, "--data-dir", str(self.data), *arguments]
        result = subprocess.run(command, capture_output=True, text=True, check=False,
                                env=env, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def config(self):
        return json.loads((self.data / "config.json").read_text())

    def save_config(self, value):
        (self.data / "config.json").write_text(json.dumps(value))

    def approved_fixture(self):
        """Simulated approval tests consistency only; this is not a real RD approval."""
        self.run_cli("new-bug", "--bug-id", "BUG-001")
        directory = self.data / "bugs/BUG-001"
        bug = json.loads((directory / "bug.json").read_text())
        bug.update({"status": "waiting_rd_approval", "baselines": {"web": "a" * 40, "server": "b" * 40},
                    "root_cause": {"version": 1, "status": "confirmed", "input_revision": 1},
                    "plan": {"version": 2, "status": "approved", "root_cause_version": 1},
                    "acceptance": {"version": 1, "plan_version": 2}})
        (directory / "bug.json").write_text(json.dumps(bug))
        for name, contents in {"analysis.md": "Confirmed synthetic cause", "plan.md": "Synthetic plan v2",
                               "acceptance.md": "Synthetic behavior assertions"}.items():
            (directory / name).write_text(contents)
        hashes = self.run_cli("artifact-hashes", "--bug-id", "BUG-001")["artifact_sha256"]
        approval = {"bug_id": "BUG-001", "decision": "approved", "input_revision": 1,
                    "root_cause_version": 1, "plan_version": 2, "acceptance_version": 1,
                    "baselines": bug["baselines"], "artifact_sha256": hashes,
                    "actor": {"id": "test-only-rd", "role": "RD"},
                    "approved_at": "2026-09-30T12:00:00+00:00",
                    "source": {"kind": "codex_user_message", "reference": "synthetic-fixture"}}
        (directory / "approval.json").write_text(json.dumps(approval))
        return directory

    def test_reinitialization_preserves_user_configuration(self):
        cfg = self.config()
        cfg["feishu"]["table_id"] = "user-configured-table"
        self.save_config(cfg)
        report = self.run_cli("init")
        self.assertEqual(report["action"], "preserved")
        self.assertEqual(self.config()["feishu"]["table_id"], "user-configured-table")

    def test_doctor_distinguishes_configuration_from_connection(self):
        cfg = self.config()
        cfg["feishu"].update({"base_url": "http://127.0.0.1:8123/base/test",
                              "table_id": "synthetic-table", "field_map": {"title": "synthetic-field"}})
        self.save_config(cfg)
        report = self.run_cli("doctor")
        self.assertFalse(report["ready_for_full_workflow"])
        self.assertEqual(report["external_connections"], "not_checked")
        self.assertFalse(report["automatic_trigger_available"])
        self.assertTrue(report["integrations_configured"]["feishu"])
        cfg["feishu"]["base_url"] = None
        self.save_config(cfg)
        self.assertFalse(self.run_cli("doctor")["integrations_configured"]["feishu"])

    def test_dossier_preserves_existing_work_and_contains_paths(self):
        self.run_cli("new-bug", "--bug-id", "BUG-001")
        analysis = self.data / "bugs/BUG-001/analysis.md"
        analysis.write_text("QA analysis already completed")
        self.assertEqual(self.run_cli("new-bug", "--bug-id", "BUG-001")["action"], "preserved")
        self.assertEqual(analysis.read_text(), "QA analysis already completed")
        self.run_cli("new-bug", "--bug-id", "../escaped", expected=2)
        self.assertFalse((self.data / "escaped").exists())

    def test_local_file_log_config_does_not_claim_files_were_read(self):
        cfg = self.config()
        cfg["log_sources"] = [{"name": "computer-local", "transport": "files", "environment": "local",
                               "paths": [str(self.base / "missing-computer.log")]}]
        environment = dict(os.environ, HOME=str(self.base), TMPDIR=str(self.base), TEMP=str(self.base))
        for path in (str(self.base / "missing-computer.log"), "~/missing-computer.log",
                     "${TMPDIR}/missing-computer.log", "${TEMP}/missing-computer.log"):
            with self.subTest(path=path):
                cfg["log_sources"][0]["paths"] = [path]
                self.save_config(cfg)
                report = self.run_cli("doctor", env=environment)
                self.assertTrue(report["integrations_configured"]["logs"])
                self.assertEqual(report["log_sources"][0]["source_access"], "not_checked")
        self.assertFalse((self.base / "missing-computer.log").exists())

    def test_explicit_log_paths_do_not_fall_back_to_another_computer(self):
        cfg = self.config()
        cfg["log_sources"] = [{"name": "computer-local", "transport": "files", "environment": "local",
                               "paths": [], "default_root": "~/.tutti-amp",
                               "relative_paths": ["computer/logs/desktopd.log"]}]
        self.save_config(cfg)
        self.assertFalse(self.run_cli("doctor")["integrations_configured"]["logs"])
        cfg["log_sources"][0]["paths"] = ["relative/computer.log"]
        self.save_config(cfg)
        self.assertFalse(self.run_cli("doctor")["integrations_configured"]["logs"])
        cfg["log_sources"][0]["paths"] = ["${TMPDIR}/computer.log"]
        self.save_config(cfg)
        environment = dict(os.environ)
        environment.pop("TMPDIR", None)
        self.assertFalse(self.run_cli("doctor", env=environment)["integrations_configured"]["logs"])
        environment["TMPDIR"] = "relative/tmp"
        self.assertFalse(self.run_cli("doctor", env=environment)["integrations_configured"]["logs"])
        del cfg["log_sources"][0]["paths"]
        self.save_config(cfg)
        self.assertTrue(self.run_cli("doctor")["integrations_configured"]["logs"])

    def test_mcp_log_config_requires_server_and_tool_and_preserves_cli_support(self):
        cfg = self.config()
        cfg["log_sources"] = [
            {"name": "web", "transport": "mcp", "environment": "test", "mcp_server": "web-logs", "tool": "query"},
            {"name": "legacy", "environment": "test", "argv": ["test-log-cli", "read"]},
        ]
        self.save_config(cfg)
        self.assertFalse(self.run_cli("doctor")["integrations_configured"]["logs"])
        cfg["mcp_servers"]["web-logs"] = {"type": "streamable-http", "url": "http://127.0.0.1:8123/mcp"}
        self.save_config(cfg)
        report = self.run_cli("doctor")
        self.assertTrue(report["integrations_configured"]["logs"])
        self.assertEqual(report["external_connections"], "not_checked")
        cfg["log_sources"][0]["tool"] = None
        self.save_config(cfg)
        self.assertFalse(self.run_cli("doctor")["integrations_configured"]["logs"])

    def test_native_webmcp_requires_a_browser_bridge_and_does_not_claim_access(self):
        cfg = self.config()
        source = {"name": "web", "transport": "browser-webmcp", "environment": "test",
                  "tool": "get_web_logs", "mcp_server": "web-logs",
                  "browser_bridge": {"kind": None, "list_pages_tool": None,
                                     "list_tools_tool": None, "execute_tool": None}}
        cfg["log_sources"] = [source]
        cfg["mcp_servers"]["web-logs"] = {"type": "streamable-http", "url": "http://127.0.0.1:8123/mcp"}
        self.save_config(cfg)
        self.assertFalse(self.run_cli("doctor")["integrations_configured"]["logs"])
        source["browser_bridge"].update({"kind": "host-tools", "list_pages_tool": "synthetic-list-pages",
                                         "list_tools_tool": "synthetic-list-tools",
                                         "execute_tool": "synthetic-execute"})
        self.save_config(cfg)
        report = self.run_cli("doctor")
        self.assertTrue(report["integrations_configured"]["logs"])
        self.assertEqual(report["log_sources"][0]["source_access"], "not_checked")
        source["browser_bridge"]["kind"] = "mcp"
        self.save_config(cfg)
        self.assertFalse(self.run_cli("doctor")["integrations_configured"]["logs"])
        source["browser_bridge"]["mcp_server"] = "web-logs"
        self.save_config(cfg)
        self.assertTrue(self.run_cli("doctor")["integrations_configured"]["logs"])
        source["browser_bridge"]["list_tools_tool"] = None
        self.save_config(cfg)
        self.assertFalse(self.run_cli("doctor")["integrations_configured"]["logs"])

    def test_unapproved_bug_is_blocked(self):
        self.run_cli("new-bug", "--bug-id", "BUG-001")
        report = self.run_cli("check-execution", "--bug-id", "BUG-001", expected=2)
        self.assertFalse(report["consistent"])
        self.assertTrue(any("approval receipt" in error for error in report["errors"]))

    def test_consistent_fixture_still_requires_identity_verification(self):
        self.approved_fixture()
        report = self.run_cli("check-execution", "--bug-id", "BUG-001")
        self.assertTrue(report["consistent"])
        self.assertFalse(report["approval_identity_verified"])

    def test_edited_plan_invalidates_prior_approval(self):
        directory = self.approved_fixture()
        (directory / "plan.md").write_text("Different plan with unchanged version number")
        report = self.run_cli("check-execution", "--bug-id", "BUG-001", expected=2)
        self.assertTrue(any("Reports changed" in error for error in report["errors"]))

    def test_new_qa_input_and_code_drift_invalidate_prior_approval(self):
        directory = self.approved_fixture()
        bug = json.loads((directory / "bug.json").read_text())
        bug["input_revision"] = 2
        bug["baselines"]["server"] = "c" * 40
        (directory / "bug.json").write_text(json.dumps(bug))
        report = self.run_cli("check-execution", "--bug-id", "BUG-001", expected=2)
        self.assertTrue(any("latest QA input" in error for error in report["errors"]))
        self.assertTrue(any("stale: baselines" in error for error in report["errors"]))

    def test_mcp_rejects_placeholders_without_overwriting_configuration(self):
        source = self.base / "plugin-source"
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns("__pycache__"))
        original = (source / "mcp.json").read_bytes()
        cfg = self.config()
        cfg["mcp_servers"] = {"web": {"type": "streamable-http", "url": "https://example.invalid/mcp"}}
        self.save_config(cfg)
        self.run_cli("configure-mcp", "--output-dir", str(source), expected=2)
        self.assertEqual((source / "mcp.json").read_bytes(), original)

    def test_mcp_generates_matching_portable_and_legacy_connections(self):
        source = self.base / "plugin-source"
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns("__pycache__"))
        cfg = self.config()
        cfg["mcp_servers"] = {
            "web": {"type": "streamable-http", "url": "http://127.0.0.1:8123/mcp"},
            "local": {"type": "stdio", "command": sys.executable, "args": ["local_server.py"]},
        }
        self.save_config(cfg)
        report = self.run_cli("configure-mcp", "--output-dir", str(source))
        self.assertEqual(report["connections"], "not_checked")
        portable = json.loads((source / "mcp.json").read_text())
        legacy = json.loads((source / ".mcp.json").read_text())
        self.assertEqual(portable["mcpServers"], cfg["mcp_servers"])
        self.assertEqual(legacy["mcpServers"]["web"], {"url": "http://127.0.0.1:8123/mcp"})

    def test_cli_refuses_unpinned_install(self):
        cfg = self.config()
        cfg["cli_dependencies"] = [{"name": "sample-cli", "command": "sample-cli", "required": True,
                                    "installer": {"type": "npm", "package": "@test/sample-cli", "version": "latest"}}]
        self.save_config(cfg)
        self.run_cli("install-cli", "--name", "sample-cli", expected=2)
        self.assertFalse((self.data / "tools/sample-cli").exists())

    @unittest.skipIf(os.name == "nt", "POSIX fake-npm fixture")
    def test_cli_install_is_private_pinned_and_idempotent(self):
        fake_bin = self.base / "fake-bin"
        fake_bin.mkdir()
        npm = fake_bin / "npm"
        npm.write_text(f"#!{sys.executable}\n" + """
import json
from pathlib import Path
import sys
args = sys.argv[1:]
prefix = Path(args[args.index('--prefix') + 1])
assert '--ignore-scripts' in args
assert args[-1] == '@test/sample-cli@1.2.3'
target = prefix / 'node_modules/.bin/sample-cli'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text('test-only executable')
target.chmod(0o755)
(prefix / 'npm-argv.json').write_text(json.dumps(args))
""")
        npm.chmod(0o755)
        environment = dict(os.environ, PATH=str(fake_bin))
        cfg = self.config()
        cfg["cli_dependencies"] = [{"name": "sample-cli", "command": "sample-cli", "required": True,
                                    "installer": {"type": "npm", "package": "@test/sample-cli", "version": "1.2.3"}}]
        self.save_config(cfg)
        report = self.run_cli("install-cli", "--name", "sample-cli", env=environment)
        self.assertEqual(report["action"], "installed")
        self.assertTrue(Path(report["executable"]).resolve().is_relative_to((self.data / "tools").resolve()))
        self.assertEqual(self.run_cli("install-cli", "--name", "sample-cli", env=environment)["action"], "reused")


if __name__ == "__main__":
    unittest.main()
