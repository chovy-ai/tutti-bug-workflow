"""CLI preparation must remain independent of login and preserve host connections."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workbench_aws_cli_test", ROOT / "scripts/workbench.py")
workbench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workbench)


class InstallerResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return "https://awscli.amazonaws.com/v2/install.sh"

    def read(self, limit):
        return self.body[:limit]


class AwsCliTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data = (Path(directory.name) / "data").resolve()
        self.data.mkdir()
        self.cfg = json.loads((ROOT.parents[1] / "config/workbench.example.json").read_text())
        self.save_config()
        self.installer = {"type":"aws-official", "version":"2.34.11"}

    def save_config(self):
        (self.data / "config.json").write_text(json.dumps(self.cfg))

    def setup_cli(self, check_auth=False):
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            status = workbench.setup_aws_cli(SimpleNamespace(config=None, install=False, check_auth=check_auth), self.data)
        return status or 0, json.loads(output.getvalue())

    def test_default_setup_reuses_cli_without_login_or_identity_calls_and_migrates_old_config(self):
        del self.cfg["aws_cli"]
        self.cfg["cli_dependencies"] = [i for i in self.cfg["cli_dependencies"] if i["name"] != "aws"]
        self.cfg["aws_mcp"]["profile"] = "synthetic-profile"
        self.cfg["custom_user_setting"] = "preserve"
        before = json.loads(json.dumps(self.cfg))
        self.save_config()
        with patch.object(workbench.shutil, "which", side_effect=lambda name: "/synthetic/aws" if name == "aws" else None), \
                patch.object(workbench.subprocess, "run", return_value=subprocess.CompletedProcess([],0,"aws-cli/2.34.11 Python/test\n","")) as run, \
                patch.object(workbench, "urlopen") as download:
            status, report = self.setup_cli()
        self.assertEqual(status, 0)
        self.assertEqual(report["installation"]["action"], "reused")
        self.assertEqual(report["authentication"], "not_checked")
        self.assertEqual(report["business_logs_access"], "not_checked")
        self.assertEqual(report["settings"]["profile"], "synthetic-profile")
        self.assertEqual([call.args[0] for call in run.call_args_list], [["/synthetic/aws", "--version"]])
        download.assert_not_called()
        after = json.loads((self.data / "config.json").read_text())
        self.assertEqual({k:v for k,v in after.items() if k not in {"aws_cli","cli_dependencies"}},
                         {k:v for k,v in before.items() if k != "cli_dependencies"})
        self.assertEqual([i for i in after["cli_dependencies"] if i["name"] != "aws"], before["cli_dependencies"])

    def test_missing_cli_can_report_installation_required_without_downloading(self):
        with patch.object(workbench.shutil, "which", return_value=None), patch.object(workbench, "urlopen") as download:
            status, report = self.setup_cli()
        self.assertEqual(status, 2)
        self.assertEqual(report["installation"]["action"], "installation_required")
        self.assertEqual(report["authentication"], "not_checked")
        download.assert_not_called()

    def test_existing_aws_dependency_without_installer_remains_discoverable_after_private_install(self):
        item = next(i for i in self.cfg["cli_dependencies"] if i["name"] == "aws")
        del item["installer"]
        item["required"] = True
        self.save_config()
        private = workbench.aws_private_executable(self.data)
        private.parent.mkdir(parents=True)
        private.write_text("synthetic executable")
        workbench.write_json(self.data / "tools/aws/installation.json", {"installer": self.installer})
        with patch.object(workbench.shutil, "which", return_value=None), \
                patch.object(workbench.subprocess, "run", return_value=subprocess.CompletedProcess([],0,"aws-cli/2.34.11 Python/test", "")):
            _, report = self.setup_cli()
        after = json.loads((self.data / "config.json").read_text())
        saved = next(i for i in after["cli_dependencies"] if i["name"] == "aws")
        self.assertTrue(saved["required"])
        self.assertEqual(saved["installer"], self.installer)
        with patch.object(workbench.shutil, "which", return_value=None):
            self.assertEqual(workbench.installed_command(self.data, saved), report["installation"]["executable"])

    def test_changed_official_script_is_not_executed(self):
        with patch.object(workbench.shutil, "which", return_value=None), \
                patch.object(workbench.platform, "system", return_value="Darwin"), \
                patch.object(workbench, "urlopen", return_value=InstallerResponse(b"changed installer")), \
                patch.object(workbench.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "script changed"):
                workbench.ensure_aws_cli(self.data, self.installer, install=True)
        run.assert_not_called()
        self.assertFalse((self.data / "tools/aws/installation.json").exists())

    def simulated_install(self, installed_version):
        body = b"synthetic reviewed official installer"
        private = workbench.aws_private_executable(self.data)
        calls = []

        def run(command, **kwargs):
            calls.append((command,kwargs))
            if "--version" in command and command[0] == "/synthetic/bash":
                private.parent.mkdir(parents=True,exist_ok=True)
                private.write_text("synthetic executable")
                return subprocess.CompletedProcess(command,0,"","")
            return subprocess.CompletedProcess(command,0,"aws-cli/"+installed_version+" Python/test\n","")

        patches = [
            patch.object(workbench.shutil, "which", side_effect=lambda name: "/synthetic/bash" if name == "bash" else None),
            patch.object(workbench.platform, "system", return_value="Darwin"),
            patch.dict(workbench.AWS_INSTALLERS, {"unix":("https://awscli.amazonaws.com/v2/install.sh",hashlib.sha256(body).hexdigest())}),
            patch.object(workbench, "urlopen", return_value=InstallerResponse(body)),
            patch.object(workbench.subprocess, "run", side_effect=run),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return calls, patches[3]

    def test_install_is_versioned_local_and_idempotent(self):
        calls,_ = self.simulated_install("2.34.11")
        first = workbench.ensure_aws_cli(self.data,self.installer,install=True)
        self.assertEqual(first["action"],"installed")
        shell_call = next(c for c in calls if c[0][0] == "/synthetic/bash")
        self.assertEqual(shell_call[0][-2:],["--version","2.34.11"])
        self.assertEqual(shell_call[1]["env"]["XDG_BIN_HOME"],str(self.data / "tools/aws/bin"))
        self.assertNotIn("sudo",shell_call[0])
        receipt = json.loads((self.data / "tools/aws/installation.json").read_text())
        self.assertEqual(receipt["installer"],self.installer)
        second = workbench.ensure_aws_cli(self.data,self.installer,install=True)
        self.assertEqual(second["action"],"reused")
        self.assertEqual(sum(c[0][0] == "/synthetic/bash" for c in calls),1)

    def test_wrong_post_install_version_does_not_record_success(self):
        self.simulated_install("2.99.1")
        with self.assertRaisesRegex(ValueError,"version check failed"):
            workbench.ensure_aws_cli(self.data,self.installer,install=True)
        self.assertFalse((self.data / "tools/aws/installation.json").exists())

    def test_optional_auth_check_preserves_profile_and_does_not_expose_identity(self):
        self.cfg["aws_cli"]["profile"] = "synthetic-profile"
        self.save_config()
        def run(command, **kwargs):
            if command[1] == "--version":
                return subprocess.CompletedProcess(command,0,"aws-cli/2.34.11 Python/test","")
            self.assertEqual(command[-2:],["--profile","synthetic-profile"])
            return subprocess.CompletedProcess(command,0,json.dumps({"Account":"test-only-account","Arn":"test-only-identity"}),"")
        with patch.object(workbench.shutil,"which",side_effect=lambda name:"/synthetic/aws" if name=="aws" else None), \
                patch.object(workbench.subprocess,"run",side_effect=run):
            _,report = self.setup_cli(check_auth=True)
        self.assertEqual(report["authentication"],"authenticated")
        self.assertNotIn("test-only-identity",json.dumps(report))
        self.assertEqual(report["business_logs_access"],"not_checked")

    def test_retirement_removes_only_the_recorded_connection(self):
        receipt = {"scope":"codex_user","registration":"configured","auth_mode":"oauth",
                   "server_name":"tutti-aws","url":"https://aws-mcp.us-east-1.api.aws/mcp?oauth=initialize"}
        workbench.write_json(self.data / "connections/aws-mcp.json",receipt)
        current = {"name":"tutti-aws","transport":{"type":"streamable_http","url":receipt["url"]}}
        servers = [current,{"name":"unrelated","transport":{"type":"stdio","command":"other"}}]
        def remove(command,**kwargs):
            self.assertEqual(command,["/synthetic/codex","mcp","remove","tutti-aws"])
            servers.remove(current)
            return subprocess.CompletedProcess(command,0,"","")
        with patch.object(workbench.shutil,"which",return_value="/synthetic/codex"), \
                patch.object(workbench,"codex_mcp_servers",side_effect=lambda codex:list(servers)), \
                patch.object(workbench.subprocess,"run",side_effect=remove):
            self.assertEqual(workbench.retire_owned_aws_mcp(self.data)["action"],"removed")
        self.assertEqual([s["name"] for s in servers],["unrelated"])
        workbench.write_json(self.data / "connections/aws-mcp.json",receipt)
        current["transport"]["http_headers"] = {"X-Custom":"user-changed"}
        with patch.object(workbench.shutil,"which",return_value="/synthetic/codex"), \
                patch.object(workbench,"codex_mcp_servers",return_value=[current]), \
                patch.object(workbench.subprocess,"run") as run:
            self.assertEqual(workbench.retire_owned_aws_mcp(self.data)["action"],"conflict_preserved")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
