"""LaunchAgent install/list/run/uninstall per assignee for scheduled fixing."""

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/schedule.py"
EXAMPLE_CONFIG = ROOT.parents[1] / "config/workbench.example.json"
USERS = [{"open_id": "ou_me", "localized_name": "韦超"}, {"open_id": "ou_z1", "localized_name": "张三"},
         {"open_id": "ou_l1", "localized_name": "李四"}, {"open_id": "ou_l2", "localized_name": "李四"}]


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.data = self.base / "data"
        self.data.mkdir()
        shutil.copyfile(EXAMPLE_CONFIG, self.data / "config.json")
        self.agents = self.base / "LaunchAgents"
        self.launchctl_log = self.base / "launchctl.log"
        fake = self.base / "launchctl"
        fake.write_text(f"#!/bin/sh\necho \"$@\" >> {self.launchctl_log}\n")
        fake.chmod(0o755)
        self.env = {**os.environ, "LARK_CLI": str(ROOT / "tests/fixtures-lark-cli.py"),
                    "FAKE_LARK_STATE": str(self.base / "lark.json"), "FAKE_LARK_USERS": json.dumps(USERS),
                    "LAUNCH_AGENTS_DIR": str(self.agents), "LAUNCHCTL": str(fake)}

    def schedule(self, *arguments, expected=0):
        data = ["--data-dir", str(self.data)] if arguments[0] != "list" else []
        result = subprocess.run([sys.executable, str(SCRIPT), arguments[0], *data, *arguments[1:]],
                                capture_output=True, text=True, timeout=30, env=self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_install_list_run_and_uninstall_per_assignee(self):
        installed = self.schedule("install", "--assignee", "张三", "--min-priority", "P1")
        self.assertEqual((installed["assignee"]["open_id"], installed["interval_seconds"]), ("ou_z1", 3600))
        plist = plistlib.loads(Path(installed["plist"]).read_bytes())
        arguments = plist["ProgramArguments"]
        self.assertEqual(arguments[1], str(ROOT / "scripts/scan.py"))
        self.assertEqual(arguments[arguments.index("--assignee") + 1], "ou_z1")
        self.assertEqual(arguments[arguments.index("--min-priority") + 1], "P1")
        self.assertEqual((plist["StartInterval"], plist["RunAtLoad"]), (3600, False))
        self.assertEqual(plist["EnvironmentVariables"]["PATH"], os.environ["PATH"])
        self.schedule("install")  # the logged-in user gets a separate job
        jobs = self.schedule("list")["jobs"]
        self.assertEqual(sorted(job["assignee"] for job in jobs), ["张三", "韦超"])
        self.schedule("run-now", "--assignee", "张三")
        self.schedule("uninstall", "--assignee", "ou_z1")
        self.assertEqual([job["assignee"] for job in self.schedule("list")["jobs"]], ["韦超"])
        calls = self.launchctl_log.read_text()
        self.assertIn("bootstrap gui/", calls)
        self.assertIn("kickstart gui/", calls)
        self.assertIn("com.tutti.bug-execute.ou_z1", calls)

    def test_ambiguous_assignee_installs_nothing(self):
        result = self.schedule("install", "--assignee", "李四", expected=1)
        self.assertEqual((result["status"], len(result["candidates"])), ("ambiguous", 2))
        self.assertFalse(self.agents.exists() and any(self.agents.iterdir()))


if __name__ == "__main__":
    unittest.main()
