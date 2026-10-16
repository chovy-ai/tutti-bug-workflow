import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/web_requests.py"
RID1 = "20261013T094940Z-88888888-2222-3333-4444-555555555555"
RID2 = "20261013T094941Z-99999999-2222-3333-4444-555555555555"
BASE = 1791625770000  # 2026-10-10T09:49:30Z


def http(at, method, url, status, level="info", source="web-http-transport", **extra):
    return {"occurredAtUnixMs": at, "kind": "http", "level": level, "source": source,
            "details": {"method": method, "url": url, "status": status}, **extra}


class WebRequestsTest(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())

    def run_script(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_failed_requests_keep_their_request_ids(self):
        log = self.base / "web-logs.log"
        log.write_text("\n".join(json.dumps(item) for item in [
            {"type": "metadata"},
            http(BASE, "GET", "https://tutti.sh/api/desktop/v2/rooms/r1", 200, requestId=RID1),
            http(BASE + 10000, "POST", "https://tutti.sh/api/desktop/v2/rooms/r1/messages", 500, "error",
                 requestId=RID1, requestIds=[RID1, RID2]),
            http(BASE + 20000, "GET", "https://tutti.sh/api/desktop/v2/agents?roomId=r1", 429, "error"),
            http(BASE, "GET", "/v1/computers/current/identity", 200, source="desktopd-http-transport"),
        ]) + "\n")
        result = self.run_script("--web-logs", str(log), "--question-time", "2026-10-10T09:49:40Z")
        self.assertEqual((result["http_requests"], result["with_request_id"], result["without_request_id"]), (3, 2, 1))
        self.assertEqual([(item["status"], item["request_ids"]) for item in result["failed_requests"]],
                         [(500, [RID1, RID2]), (429, [])])
        self.assertEqual(result["failed_requests"][0]["path"], "/v2/rooms/r1/messages")
        self.assertEqual(len(result["nearest_requests"]), 3)  # always listed, failures or not

    def test_diagnostics_zip_without_failures_lists_nearest(self):
        archive = self.base / "tutti-web-diagnostics.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("logs.jsonl", json.dumps({
                "at": "2026-10-10T09:49:30.000Z", "kind": "http", "level": "info", "source": "web-http-transport",
                "requestId": RID2, "details": {"method": "GET", "url": "https://tutti.sh/api/desktop/v2/rooms/r1",
                                               "status": 200}}) + "\n")
        result = self.run_script("--web-logs", str(archive), "--question-time", "2026-10-10T09:49:40Z")
        self.assertEqual(result["failed_requests"], [])
        self.assertEqual(result["nearest_requests"][0]["request_ids"], [RID2])

    def test_diagnostics_zip_counts_each_record_once_and_windows_failures(self):
        old = http(BASE - 3600000, "GET", "https://tutti.sh/api/desktop/v2/rooms/r1", 502, "error", requestId=RID1)
        near = http(BASE, "POST", "https://tutti.sh/api/desktop/v2/rooms/r1/messages", 500, "error", requestId=RID2)
        ok = http(BASE + 5000, "GET", "https://tutti.sh/api/desktop/v2/rooms/r1", 200)
        archive = self.base / "tutti-web-diagnostics.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("logs.jsonl", "\n".join(json.dumps(item) for item in (old, near, ok)) + "\n")
            zipped.writestr("errors.jsonl", "\n".join(json.dumps(item) for item in (old, near)) + "\n")
        result = self.run_script("--web-logs", str(archive), "--incident-at", "2026-10-10T09:49:40Z")
        self.assertEqual(result["http_requests"], 3)
        self.assertEqual([item["request_ids"] for item in result["failed_requests"]], [[RID2]])
        self.assertEqual([item["request_ids"] for item in result["failed_outside_window"]], [[RID1]])
        self.assertEqual(len(result["nearest_requests"]), 3)
        with zipfile.ZipFile(archive, "w") as zipped:  # an export without logs.jsonl still reads errors.jsonl
            zipped.writestr("errors.jsonl", json.dumps(near) + "\n")
        self.assertEqual(self.run_script("--web-logs", str(archive))["http_requests"], 1)

    def test_invalid_input(self):
        self.run_script("--web-logs", str(self.base / "missing.log"), expected=2)
        log = self.base / "web-logs.log"
        log.write_text("")
        self.run_script("--web-logs", str(log), "--question-time", "2026-10-10T09:49:40", expected=2)


if __name__ == "__main__":
    unittest.main()
