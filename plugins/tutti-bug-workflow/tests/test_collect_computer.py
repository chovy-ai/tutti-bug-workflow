"""collect_computer.py against fake tutti-ops / tutti-computer; no network or real devices."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "scripts/workbench.py"
SCRIPT = ROOT / "scripts/collect_computer.py"
FAKE = ROOT / "tests/fixtures-tutti-ops.py"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def at(minutes):
    """UTC timestamp relative to now, so the tests never age past the 14-day range."""
    return (NOW + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


INCIDENT = at(-30)  # window: -40..-30 minutes


def task(state, start=at(-60), end=at(-5), **extra):
    return {"taskId": "task-old", "state": state, "requestedStartAt": start, "requestedEndAt": end,
            "actualStartAt": start, "actualEndAt": end, "truncated": False, "unknownTimestampRows": "0",
            "createdAt": at(-5), "deadlineAt": "2999-01-01T00:00:00Z", **extra}


class CollectComputerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.data = self.base / "data"
        self.out = self.base / "out"
        self.state_path = self.base / "ops.json"
        subprocess.run([sys.executable, str(WORKBENCH), "init", "--data-dir", str(self.data)],
                       check=True, capture_output=True)
        self.package = self.base / "package.tar.gz"
        self.write_package({"desktopd.log": b"2026-10-09T03:55:00Z error\n", "manifest.json": b"{}"})
        self.env = {**os.environ, "TUTTI_OPS": str(FAKE), "TUTTI_COMPUTER": str(FAKE),
                    "FAKE_OPS_STATE": str(self.state_path), "COLLECT_COMPUTER_ALLOW_FILE_URL": "1"}

    def write_package(self, members, link=None):
        with tarfile.open(self.package, "w:gz") as archive:
            for name, content in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(content)
                archive.addfile(info, io.BytesIO(content))
            if link:
                info = tarfile.TarInfo(link)
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                archive.addfile(info)
        self.sha = hashlib.sha256(self.package.read_bytes()).hexdigest()

    def state(self, **values):
        base = {"tasks": [], "package": str(self.package), "local_computer_id": "other",
                "new_task": task(1, start=at(-180), end=at(0), sha256=self.sha)}
        self.state_path.write_text(json.dumps({**base, **values}))

    def collect(self, *extra):
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data),
                                 "--computer-id", "c-1", "--incident-at", INCIDENT,
                                 "--output-dir", str(self.out), "--poll-seconds", "0", *extra],
                                capture_output=True, text=True, timeout=60, env=self.env, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def calls(self):
        return json.loads(self.state_path.read_text())["calls"]

    def test_reuses_downloadable_recall_and_extracts_verified_package(self):
        self.state(tasks=[task("COMPUTER_RUNTIME_LOG_RECALL_STATE_DOWNLOADABLE", sha256=self.sha)])
        result = self.collect()
        self.assertEqual((result["status"], result["source"], result["recall"]), ("captured", "remote", "reused"))
        self.assertEqual(result["files"][0]["name"], "Dev_s_Mac_logs.tar.gz")
        self.assertEqual(result["files"][0]["sha256"], self.sha)
        self.assertTrue((Path(result["extracted_dir"]) / "desktopd.log").is_file())
        self.assertNotIn("create", self.calls())

    def test_creates_smallest_covering_recall_and_waits_until_downloadable(self):
        self.state(tasks=[task(3, start=at(-35), sha256=self.sha)],
                   progress=[{"state": 2}, {"state": 3}])
        result = self.collect()
        self.assertEqual((result["status"], result["recall"]), ("captured", "created"))
        state = json.loads(self.state_path.read_text())
        self.assertEqual(state["calls"].count("get"), 2)
        self.assertEqual(state["created_preset"], 1)  # 1 hour covers 40 minutes + margin

    def test_joins_running_recall_instead_of_creating_another(self):
        self.state(tasks=[task(1, sha256=self.sha)], progress=[{"state": 3}])
        result = self.collect()
        self.assertEqual(result["recall"], "joined")
        self.assertNotIn("create", self.calls())

    def test_failures_are_reported_as_blocked(self):
        cases = [
            ({"tasks": [task(3, sha256="0" * 64)]}, (), "SHA-256 does not match"),
            ({"tasks": [task(1)], "progress": [{"state": 4, "failureCode": "DEVICE_OFFLINE"}]}, (), "DEVICE_OFFLINE"),
            ({}, ("--no-create",), "--no-create"),
            ({"create_fails": True}, (), "permission denied"),
        ]
        for values, extra, reason in cases:
            with self.subTest(reason=reason):
                self.state(**values)
                result = self.collect(*extra)
                self.assertEqual(result["status"], "blocked")
                self.assertIn(reason, result["reason"])

    def test_unsafe_archive_and_old_incident_are_blocked(self):
        self.write_package({"desktopd.log": b"x"}, link="evil")
        self.state(tasks=[task(3, sha256=self.sha)])
        self.assertIn("links or paths", self.collect()["reason"])
        self.state()
        result = json.loads(subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data),
                                            "--computer-id", "c-1", "--incident-at", "2020-01-01T00:00:00Z",
                                            "--output-dir", str(self.out)], capture_output=True, text=True,
                                           env=self.env, check=False).stdout)
        self.assertIn("older than the 14-day", result["reason"])

    def test_local_computer_copies_configured_files(self):
        log = self.base / "desktopd.log"
        log.write_text("local\n")
        config = json.loads((self.data / "config.json").read_text())
        for source in config["log_sources"]:
            if source["name"] == "computer-local":
                source["paths"] = [str(log), str(self.base / "missing.log")]
        (self.data / "config.json").write_text(json.dumps(config))
        self.state(local_computer_id="c-1")
        result = self.collect()
        self.assertEqual((result["source"], result["status"]), ("local", "partial"))
        self.assertEqual([item["name"] for item in result["files"]], ["desktopd.log"])
        self.assertTrue(any("missing.log" in gap for gap in result["gaps"]))

    def test_invalid_incident_time_is_rejected(self):
        self.state()
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data), "--computer-id", "c-1",
                                 "--incident-at", "2026-10-09T12:00:00", "--output-dir", str(self.out)],
                                capture_output=True, text=True, env=self.env, check=False)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
