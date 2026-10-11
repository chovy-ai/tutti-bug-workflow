"""collect_server.py with a fake aws CLI; no network."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "scripts/collect_server.py"
FAKE = ROOT / "tests/fixtures-aws.py"
RID1 = "20261010T094855Z-4bfd1111-2222-3333-4444-fa347ac78d1b"
RID2 = "20261010T094900Z-aaaa1111-2222-3333-4444-bbbbbbbbbbbb"
ROWS = [
    {"@timestamp": "2026-10-10 09:49:00.000", "kubernetes.namespace_name": "lane-ppe-cloud-0928",
     "kubernetes.pod_name": "p1", "log": f"INFO request_id={RID2} route=/v2/rooms status_code=500"},
    {"@timestamp": "2026-10-10 09:48:55.000", "kubernetes.namespace_name": "lane-ppe-cloud-0928",
     "kubernetes.pod_name": "p1", "log": f"INFO request_id={RID1} route=/v2/rooms status_code=200"},
    {"@timestamp": "2026-10-10 09:48:00.000", "kubernetes.namespace_name": "tutti",
     "kubernetes.pod_name": "p2", "log": "INFO request_id=other route=/v2/x"},
]


class CollectServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.env = {**os.environ, "AWS_CLI": str(FAKE), "FAKE_AWS_STATE": str(self.base / "aws.json"),
                    "FAKE_AWS_ROWS": json.dumps(ROWS)}

    def server(self, *extra, env=None, expected=0):
        result = subprocess.run([sys.executable, str(SERVER), "--question-time", "2026-10-10T09:50:00Z",
                                 "--output-dir", str(self.base / "out"), "--poll-seconds", "0", *extra],
                                capture_output=True, text=True, timeout=30, env=env or self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_request_ids_find_logs_sorted_with_environment(self):
        result = self.server("--request-id", RID2, "--request-id", RID1, "--request-id", RID1)
        self.assertEqual((result["status"], result["record_count"], result["matched_request_ids"]), ("captured", 2, 2))
        self.assertEqual((result["namespaces"], result["environments"]), (["lane-ppe-cloud-0928"], ["PPE"]))
        lines = (self.base / "out/server-logs.log").read_text().splitlines()
        self.assertEqual(json.loads(lines[0])["type"], "metadata")
        self.assertIn(RID1, json.loads(lines[1])["log"])

    def test_empty_blocked_and_invalid_inputs(self):
        self.assertEqual(self.server("--request-id", "20261010T000000Z-00000000-0000-0000-0000-000000000000")["status"], "empty")
        failing = {**self.env, "FAKE_AWS_FAIL": "1"}
        self.assertEqual(self.server("--request-id", RID1, env=failing)["status"], "blocked")
        self.server(expected=2)
        self.server("--path-contains", 'x" or 1=1', expected=2)

    def test_many_ids_are_batched(self):
        ids = [f"20261010T0948{i:02d}Z-4bfd1111-2222-3333-4444-fa347ac78d{i:02d}" for i in range(45)]
        self.server(*[arg for rid in ids for arg in ("--request-id", rid)])
        self.assertEqual(len(json.loads((self.base / "aws.json").read_text())["queries"]), 3)

    def test_request_ids_are_read_from_web_logs_and_diagnostics_zip(self):
        log = self.base / "web-logs.log"
        log.write_text(json.dumps({"requestId": RID1, "event": "http"}) + "\n")
        archive = self.base / "tutti-web-diagnostics.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("logs.jsonl", json.dumps({"requestId": RID2}) + "\n")
            zipped.writestr("manifest.json", "{}")
        result = self.server("--web-logs", str(log), "--web-logs", str(archive))
        self.assertEqual((result["request_ids"], result["matched_request_ids"]), (2, 2))
        empty = self.base / "empty.log"
        empty.write_text("no ids here")
        self.server("--web-logs", str(empty), expected=2)


if __name__ == "__main__":
    unittest.main()
