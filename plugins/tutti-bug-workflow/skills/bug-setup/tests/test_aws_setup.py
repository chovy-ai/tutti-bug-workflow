"""Exercise native MCP registration boundaries using synthetic host executables."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/workbench.py"


class AwsSetupTests(unittest.TestCase):
    auth_mode = "sigv4"
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name)
        self.data = self.base / "data"
        self.state_path = self.base / "host.json"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.environment = dict(os.environ, PATH=str(self.bin), MOCK_AWS_STATE_FILE=str(self.state_path))
        executable = '''import json, os, pathlib, sys
path = pathlib.Path(os.environ["MOCK_AWS_STATE_FILE"])
state = json.loads(path.read_text())
tool, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
state["calls"].append([tool, *args])
path.write_text(json.dumps(state))
if tool == "uvx":
    if state.get("runtime_failure"):
        sys.exit(1)
    print("--read-only")
elif tool == "aws":
    if state.get("sso_expired"):
        print("Error when retrieving token from sso: Token has expired and refresh failed", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"Account":"synthetic-account", "Arn":"synthetic-identity"}))
elif args[:2] == ["mcp", "list"]:
    print(json.dumps(state["servers"]))
elif args[:2] == ["mcp", "add"]:
    if state.get("add_failure") and not state.get("persist_then_fail"):
        sys.exit(1)
    if "--url" in args:
        server = {"name":args[2], "enabled":True, "auth_status":state.get("auth_status", "not_logged_in"),
            "transport":{"type":"streamable_http", "url":args[args.index("--url")+1],
                         "bearer_token_env_var":None, "http_headers":None, "env_http_headers":None}}
    else:
        start = args.index("--") + 1
        server = {"name":args[2], "enabled":True,
            "transport":{"type":"stdio", "command":args[start], "args":args[start+1:],
                         "env":None, "env_vars":[], "cwd":None}}
    state["servers"] = [s for s in state["servers"] if s["name"] != args[2]] + [server]
    path.write_text(json.dumps(state))
    if state.get("add_failure"):
        sys.exit(1)
else:
    sys.exit(2)
'''
        for name in ("codex", "uvx", "aws"):
            file = self.bin / name
            file.write_text("#!" + sys.executable + "\n" + executable)
            file.chmod(0o755)
        self.save_state({"servers": [], "calls": []})
        self.run_cli("init")
        cfg_path = self.data / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["aws_mcp"]["auth_mode"] = self.auth_mode
        cfg_path.write_text(json.dumps(cfg))

    def state(self):
        return json.loads(self.state_path.read_text())

    def save_state(self, value):
        self.state_path.write_text(json.dumps(value))

    def run_cli(self, operation, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), operation, "--data-dir", str(self.data)],
                                capture_output=True, text=True, env=self.environment, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_registration_reuses_config_preserves_other_services_and_does_not_claim_connection(self):
        unrelated = {"name": "unrelated", "enabled": True,
                     "transport": {"type": "streamable_http", "url": "https://service.invalid/mcp"}}
        state = self.state()
        state["servers"].append(unrelated)
        self.save_state(state)
        cfg_path = self.data / "config.json"
        before = json.loads(cfg_path.read_text())
        before["custom_user_setting"] = "keep-me"
        cfg_path.write_text(json.dumps(before))
        report = self.run_cli("setup-aws-mcp")
        self.assertEqual(report["action"], "registered")
        self.assertEqual(report["authentication"], "cli_credentials_valid")
        self.assertEqual(report["connection"], "not_checked")
        self.assertNotIn("synthetic-identity", json.dumps(report))
        after = json.loads(cfg_path.read_text())
        self.assertEqual(after, before)
        self.assertEqual(self.state()["servers"][0], unrelated)
        server = self.state()["servers"][1]
        self.assertIn("--read-only", server["transport"]["args"])
        self.assertIn("mcp-proxy-for-aws-cli==1.7.0", server["transport"]["args"])
        self.assertEqual(self.run_cli("setup-aws-mcp")["action"], "reused")
        self.assertEqual(sum(c[:3] == ["codex", "mcp", "add"] for c in self.state()["calls"]), 1)

    def test_name_collision_is_preserved_without_downloading_or_changing_user_config(self):
        existing = {"name":"tutti-aws", "enabled":True,
                    "transport":{"type":"stdio", "command":"different-command", "args":[]}}
        self.save_state({"servers":[existing], "calls":[]})
        before = (self.data / "config.json").read_bytes()
        report = self.run_cli("setup-aws-mcp", expected=2)
        self.assertEqual(report["registration"], "conflict_preserved")
        self.assertEqual(self.state()["servers"], [existing])
        self.assertTrue(all(c[0] == "codex" for c in self.state()["calls"]))
        self.assertEqual((self.data / "config.json").read_bytes(), before)
        self.assertFalse((self.data / "connections/aws-mcp.json").exists())

    def test_failed_runtime_preparation_does_not_register(self):
        self.save_state({"servers":[], "calls":[], "runtime_failure":True})
        report = self.run_cli("setup-aws-mcp", expected=2)
        self.assertEqual(report["registration"], "runtime_unavailable")
        self.assertEqual(self.state()["servers"], [])
        self.assertFalse(any(c[:3] == ["codex", "mcp", "add"] for c in self.state()["calls"]))

    def test_expired_sso_preserves_successful_registration_but_requires_login(self):
        self.save_state({"servers":[], "calls":[], "sso_expired":True})
        cfg_path = self.data / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["aws_mcp"]["profile"] = "test-readonly"
        cfg_path.write_text(json.dumps(cfg))
        report = self.run_cli("setup-aws-mcp")
        self.assertEqual(report["registration"], "configured")
        self.assertEqual(report["authentication"], "sso_login_required")
        self.assertEqual(report["login_command"], ["aws", "sso", "login", "--profile", "test-readonly"])
        self.assertEqual(report["connection"], "not_checked")
        aws_call = next(c for c in self.state()["calls"] if c[0] == "aws")
        self.assertEqual(aws_call[-2:], ["--profile", "test-readonly"])

    def test_native_registration_failure_does_not_write_success_receipt(self):
        self.save_state({"servers":[], "calls":[], "add_failure":True})
        report = self.run_cli("setup-aws-mcp", expected=2)
        self.assertFalse(report["ok"])
        self.assertFalse((self.data / "connections/aws-mcp.json").exists())


class AwsOauthSetupTests(AwsSetupTests):
    auth_mode = "oauth"

    def test_registration_reuses_config_preserves_other_services_and_does_not_claim_connection(self):
        unrelated = {"name":"unrelated", "enabled":True,
                     "transport":{"type":"streamable_http", "url":"https://service.invalid/mcp"}}
        self.save_state({"servers":[unrelated], "calls":[]})
        # OAuth must work when neither AWS CLI nor uvx is installed.
        (self.bin / "aws").unlink()
        (self.bin / "uvx").unlink()
        cfg_path = self.data / "config.json"
        before = json.loads(cfg_path.read_text())
        del before["aws_mcp"]
        before["custom_user_setting"] = "keep-me"
        cfg_path.write_text(json.dumps(before))
        report = self.run_cli("setup-aws-mcp")
        self.assertEqual(report["action"], "registered")
        self.assertEqual(report["authentication"], "oauth_login_required")
        self.assertEqual(report["connection"], "not_checked")
        self.assertFalse(report["read_only_enforced"])
        self.assertEqual(report["login_command"], ["codex", "mcp", "login", "tutti-aws"])
        after = json.loads(cfg_path.read_text())
        self.assertEqual({k:v for k,v in after.items() if k != "aws_mcp"}, before)
        self.assertEqual(self.state()["servers"][0], unrelated)
        self.assertEqual(self.state()["servers"][1]["transport"]["url"],
                         "https://aws-mcp.us-east-1.api.aws/mcp?oauth=initialize")
        self.assertEqual(self.run_cli("setup-aws-mcp")["action"], "reused")
        self.assertTrue(all(c[0] == "codex" for c in self.state()["calls"]))
        self.assertEqual(sum(c[:3] == ["codex", "mcp", "add"] for c in self.state()["calls"]), 1)

    def test_failed_runtime_preparation_does_not_register(self):
        # Legacy runtime failures do not participate in remote OAuth setup.
        self.save_state({"servers":[], "calls":[], "runtime_failure":True})
        report = self.run_cli("setup-aws-mcp")
        self.assertEqual(report["registration"], "configured")
        self.assertFalse(any(c[0] == "uvx" for c in self.state()["calls"]))

    def test_expired_sso_preserves_successful_registration_but_requires_login(self):
        self.save_state({"servers":[], "calls":[], "sso_expired":True, "auth_status":"oauth"})
        report = self.run_cli("setup-aws-mcp")
        self.assertEqual(report["authentication"], "oauth_credentials_present")
        self.assertEqual(report["connection"], "not_checked")
        self.assertFalse(any(c[0] == "aws" for c in self.state()["calls"]))

    def test_persisted_registration_survives_oauth_failure_without_claiming_login(self):
        self.save_state({"servers":[], "calls":[], "add_failure":True, "persist_then_fail":True})
        report = self.run_cli("setup-aws-mcp")
        self.assertEqual(report["registration"], "configured")
        self.assertEqual(report["add_status"], "auth_or_registration_error")
        self.assertEqual(report["authentication"], "oauth_login_required")

    def test_migrates_only_unchanged_plugin_owned_legacy_proxy(self):
        cfg_path = self.data / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["aws_mcp"]["auth_mode"] = "sigv4"
        cfg_path.write_text(json.dumps(cfg))
        self.assertEqual(self.run_cli("setup-aws-mcp")["action"], "registered")
        del cfg["aws_mcp"]["auth_mode"]  # 0.1.12 had no auth_mode; upgrade defaults to OAuth.
        cfg_path.write_text(json.dumps(cfg))
        self.assertEqual(self.run_cli("setup-aws-mcp")["action"], "migrated_to_oauth")
        self.assertEqual(len(self.state()["servers"]), 1)
        self.assertEqual(self.state()["servers"][0]["transport"]["type"], "streamable_http")

    def test_modified_legacy_proxy_is_preserved(self):
        cfg_path = self.data / "config.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["aws_mcp"]["auth_mode"] = "sigv4"
        cfg_path.write_text(json.dumps(cfg))
        self.run_cli("setup-aws-mcp")
        state = self.state()
        state["servers"][0]["transport"]["args"].append("--custom-user-option")
        self.save_state(state)
        cfg["aws_mcp"]["auth_mode"] = "oauth"
        cfg_path.write_text(json.dumps(cfg))
        report = self.run_cli("setup-aws-mcp", expected=2)
        self.assertEqual(report["registration"], "conflict_preserved")
        self.assertEqual(self.state()["servers"], state["servers"])


if __name__ == "__main__":
    unittest.main()
