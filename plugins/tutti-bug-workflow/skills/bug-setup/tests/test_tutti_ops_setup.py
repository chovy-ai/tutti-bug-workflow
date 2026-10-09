"""Exercise global CLI preparation in an isolated fake npm prefix, without login."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/workbench.py"


@unittest.skipIf(os.name == "nt", "POSIX executable fixtures")
class TuttiOpsSetupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.bin = self.base / "bin"
        self.global_prefix = self.base / "global"
        self.bin.mkdir()
        self.env = dict(os.environ, PATH=str(self.bin))
        self.invoke("init")
        self.write_executable(self.bin / "node", "print('v24.14.0')\n")
        cli_body = """import sys
if sys.argv[1:] == ['computer', '--help']:
    print('Computer commands: devices, log-recalls')
else:
    raise SystemExit('Unexpected operation, including authentication')
"""
        npm_body = f"""import json
from pathlib import Path
import sys
args = sys.argv[1:]
base = Path({str(self.base)!r})
prefix = Path({str(self.global_prefix)!r})
with (base / 'npm-calls.jsonl').open('a') as stream:
    stream.write(json.dumps(args) + '\\n')
if args == ['prefix', '-g']:
    print(prefix)
elif args == ['install', '-g', '@tutti-os/tutti-ops-cli']:
    package = prefix / 'lib/node_modules/@tutti-os/tutti-ops-cli'
    entrypoint = package / 'dist/index.js'
    entrypoint.parent.mkdir(parents=True, exist_ok=True)
    entrypoint.write_text({('#!' + sys.executable + chr(10) + cli_body)!r})
    entrypoint.chmod(0o755)
    (package / 'package.json').write_text(json.dumps({{'name':'@tutti-os/tutti-ops-cli','version':'0.1.6'}}))
    executable = prefix / 'bin/tutti-ops'
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.symlink_to(entrypoint)
else:
    raise SystemExit('Wrong package or installation scope')
"""
        self.write_executable(self.bin / "npm", npm_body)

    def write_executable(self, path, body):
        path.write_text("#!" + sys.executable + "\n" + body)
        path.chmod(0o755)

    def invoke(self, operation, *arguments, expected=0):
        output = subprocess.run([sys.executable, str(SCRIPT), operation, "--data-dir", str(self.data),
                                 *arguments], capture_output=True, text=True, env=self.env, timeout=20)
        self.assertEqual(output.returncode, expected, output.stdout + output.stderr)
        return json.loads(output.stdout)

    def config(self):
        return json.loads((self.data / "config.json").read_text())

    def save_config(self, value):
        (self.data / "config.json").write_text(json.dumps(value))

    def test_setup_installs_globally_reuses_out_of_path_binary_and_preserves_old_config(self):
        config = self.config()
        item = next(item for item in config["cli_dependencies"] if item["name"] == "tutti-ops")
        item.update(required=False, installer=None)
        config["custom_setting"] = "preserve"
        self.save_config(config)
        first = self.invoke("setup-tutti-ops", "--install")
        self.assertTrue(first["ok"])
        self.assertEqual(first["installation"]["action"], "installed")
        self.assertEqual(first["installation"]["version"], "0.1.6")
        self.assertTrue(Path(first["installation"]["executable"]).is_relative_to(self.global_prefix))
        self.assertEqual(first["authentication"], "not_checked")
        self.assertEqual(first["business_logs_access"], "not_checked")
        calls = (self.base / "npm-calls.jsonl").read_text()
        second = self.invoke("setup-tutti-ops", "--install")
        self.assertEqual(second["installation"]["action"], "reused")
        self.assertEqual((self.base / "npm-calls.jsonl").read_text(), calls)
        report = self.invoke("doctor")
        declared = next(item for item in report["cli_dependencies"] if item["name"] == "tutti-ops")
        self.assertEqual(declared["executable"], first["installation"]["executable"])
        self.assertTrue(declared["available"])
        after = self.config()
        self.assertEqual({k: v for k, v in after.items() if k != "cli_dependencies"},
                         {k: v for k, v in config.items() if k != "cli_dependencies"})
        self.assertEqual([item for item in after["cli_dependencies"] if item["name"] != "tutti-ops"],
                         [item for item in config["cli_dependencies"] if item["name"] != "tutti-ops"])

    def test_check_without_install_does_not_run_npm_or_claim_connection(self):
        result = self.invoke("setup-tutti-ops", expected=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["installation"]["action"], "installation_required")
        self.assertEqual(result["authentication"], "not_checked")
        self.assertFalse((self.base / "npm-calls.jsonl").exists())

    def test_unsupported_node_prevents_global_changes(self):
        self.write_executable(self.bin / "node", "print('v18.20.0')\n")
        result = self.invoke("setup-tutti-ops", "--install", expected=2)
        self.assertIn("Node.js >=20", result["error"])
        self.assertFalse((self.base / "npm-calls.jsonl").exists())
        self.assertFalse(self.global_prefix.exists())

    def test_install_failure_has_no_success_receipt_and_keeps_diagnostics(self):
        self.write_executable(self.bin / "npm", "import sys\nprint('permission denied', file=sys.stderr)\nsys.exit(1)\n")
        result = self.invoke("setup-tutti-ops", "--install", expected=2)
        self.assertIn("installation failed", result["error"])
        self.assertFalse((self.data / "tools/tutti-ops/installation.json").exists())
        self.assertIn("permission denied", (self.data / "tools/tutti-ops/npm-install.stderr.log").read_text())

    def test_custom_configuration_is_preserved_without_installation(self):
        config = self.config()
        next(item for item in config["cli_dependencies"] if item["name"] == "tutti-ops")["command"] = "custom-ops"
        self.save_config(config)
        self.invoke("setup-tutti-ops", "--install", expected=2)
        self.assertEqual(self.config(), config)
        self.assertFalse((self.base / "npm-calls.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
