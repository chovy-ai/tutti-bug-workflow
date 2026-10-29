"""Validate browser-downloaded log snapshots at the filesystem/CLI boundary."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/merge_web_logs.py"
PAGE = "web-diagnostics:95eafceb-4246-4616-b8ca-15bcbb8eff14"
LINK = f"tutti-webmcp://page/{PAGE}?accountId=user-a"
QUESTION = "2026-10-08T23:00:00Z"
UNTIL = 1791500400000  # 2026-10-08T23:00:00Z
SINCE = UNTIL - 600000


def record(rid, offset, account="user-a"):
    return {"id": rid, "occurredAtUnixMs": UNTIL - offset, "pageSessionId": PAGE, "userId": account,
            "level": "info", "event": f"e{rid}"}


def snapshot(records, truncated=False, account="user-a", since=SINCE):
    return {"pageSessionId": PAGE, "accountId": account, "sinceUnixMs": since, "untilUnixMs": UNTIL,
            "redacted": False, "records": records, "truncated": truncated, "retention": "current-page-memory"}


class MergeWebLogsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def test_identity_and_window_errors_are_rejected(self):
        self.run_download(snapshot([record(1, 1000)], account="user-b"), expected=2)
        self.run_download(snapshot([record(1, 1000)], since=SINCE - 1), expected=2)
        self.run_download(snapshot([record(1, 700000)]), expected=2)
        self.run_download({"status": "Error", "errorText": "denied"}, expected=2)

    def test_removed_pagination_argument_is_rejected(self):
        path = self.base / "old-page.json"
        path.write_text(json.dumps(snapshot([record(1, 1000)])))
        result = subprocess.run([sys.executable, str(SCRIPT), "--connection-url", LINK,
                                 "--question-time", QUESTION, "--page", str(path),
                                 "--output", str(self.base / "web-logs.log")],
                                capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((self.base / "web-logs.log").exists())

    def test_until_ms_comes_from_the_same_question_time(self):
        result = subprocess.run([sys.executable, str(SCRIPT), "--question-time", "2026-10-09T07:00:00.250+08:00",
                                 "--until-ms"], capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(json.loads(result.stdout)["untilUnixMs"], UNTIL + 250)
        self.assertEqual(json.loads(subprocess.run(
            [sys.executable, str(SCRIPT), "--question-time", QUESTION, "--until-ms"],
            capture_output=True, text=True, timeout=20, check=False).stdout)["untilUnixMs"], UNTIL)

    def test_late_report_reads_up_to_five_minutes_after_the_incident(self):
        def until(*extra):
            return json.loads(subprocess.run([sys.executable, str(SCRIPT), "--question-time", QUESTION, *extra,
                                              "--until-ms"], capture_output=True, text=True, timeout=20,
                                             check=False).stdout)["untilUnixMs"]
        self.assertEqual(until("--incident-at", "2026-10-08T22:30:00Z"), UNTIL - 30 * 60000 + 5 * 60000)
        self.assertEqual(until("--incident-at", "2026-10-08T22:58:00Z"), UNTIL)  # capped by the report time
        page = snapshot([record(1, 1000)], False)
        page["untilUnixMs"], page["sinceUnixMs"] = UNTIL - 25 * 60000, UNTIL - 85 * 60000
        # Include the previously lost pre-incident request, both boundaries, and older noise.
        page["records"] = [record(4, 25 * 60000), record(3, 38 * 60000),
                           record(2, 40 * 60000), record(1, 41 * 60000)]
        result = self.run_download(page, extra=("--incident-at", "2026-10-08T22:30:00Z"))
        self.assertEqual((result["incidentAt"], result["recordCount"]), ("2026-10-08T22:30:00Z", 3))

    def test_recent_report_uses_wide_read_but_caps_output_at_report(self):
        incident = "2026-10-08T22:58:00Z"
        result = json.loads(subprocess.run(
            [sys.executable, str(SCRIPT), "--question-time", QUESTION, "--incident-at", incident, "--until-ms"],
            capture_output=True, text=True, check=True).stdout)
        self.assertEqual((result["range"], result["untilUnixMs"], result["sinceUnixMs"]),
                         ("1h", UNTIL, UNTIL - 12 * 60000))
        page = snapshot([record(2, 11 * 60000), record(1, 13 * 60000)], False, since=UNTIL - 60 * 60000)
        merged = self.run_download(page, extra=("--incident-at", incident))
        self.assertEqual((merged["sinceUnixMs"], merged["recordCount"]), (UNTIL - 12 * 60000, 1))
        # Old callers that still read only 10 minutes must not silently produce a complete file.
        self.run_download(snapshot([], False), extra=("--incident-at", incident), expected=2)

    def test_window_mismatch_names_both_values(self):
        page = snapshot([record(1, 1000)], False)
        page["untilUnixMs"] = UNTIL + 594
        error = self.run_download(page, expected=2)["error"]
        self.assertIn(str(UNTIL + 594), error)
        self.assertIn(str(UNTIL), error)
        self.assertIn("--until-ms", error)

    def test_page_identity_without_link_still_checks_the_account(self):
        page = snapshot([record(1, 1000)], False)
        self.run_download(page, link=PAGE, expected=2)  # no Account to check against
        self.assertEqual(self.run_download(page, link=PAGE, extra=("--account-id", "user-a"))["accountId"], "user-a")
        self.run_download(page, link=PAGE, extra=("--account-id", "user-b"), expected=2)
        self.run_download(page, extra=("--account-id", "user-b"), expected=2)  # differs from the link

    def run_download(self, value, expected=0, name="日志 export.json", extra=(), link=LINK):
        path = self.base / name
        path.write_text(json.dumps(value), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--connection-url", link, "--question-time", QUESTION,
             "--download", str(path), "--output", str(self.base / "web-logs.log"), *extra],
            capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_full_download_is_validated_without_returning_log_bodies(self):
        logs = [record(rid, 1000) for rid in range(250, 0, -1)]
        logs[0]["details"] = {"token": "original", "path": r"C:\Users\QA\Downloads"}
        downloaded = {**snapshot(logs, False), "retention": "current-page-memory"}
        result = self.run_download(downloaded)
        self.assertEqual((result["collectionStatus"], result["recordCount"]), ("complete", 250))
        self.assertNotIn("records", result)
        self.assertNotIn("original", json.dumps(result))
        lines = (self.base / "web-logs.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["id"] for line in lines[1:]], list(range(1, 251)))
        self.assertEqual(json.loads(lines[-1])["details"], logs[0]["details"])
        self.assertEqual(self.run_download({**downloaded, "records": []})["recordCount"], 0)

    def test_wrong_or_unfinished_download_is_rejected(self):
        downloaded = {**snapshot([record(1, 1000)], False), "retention": "current-page-memory"}
        for change in ({"accountId": "user-b"}, {"pageSessionId": "other-page"}, {"redacted": True},
                       {"retention": "indexeddb"}, {"truncated": True}, {"untilUnixMs": UNTIL + 1}, {"records": [record(1, 1000), record(2, 1000)]}):
            with self.subTest(change=change):
                self.run_download({**downloaded, **change}, expected=2)
        self.run_download(downloaded, expected=2, name="file.json.crdownload")
        self.run_download(downloaded, expected=2, extra=("--expected-size", "1"))
        self.run_download(downloaded, expected=2, extra=("--expected-record-count", "2"))
        result = self.run_download(downloaded, extra=("--expected-size", str(len(json.dumps(downloaded).encode())),
                                                     "--expected-record-count", "1"))
        self.assertEqual(result["recordCount"], 1)

    def test_download_keeps_late_report_window_and_request_evidence(self):
        logs = [record(2, 38 * 60000), record(1, 41 * 60000)]
        logs[0].update(kind="http", source="web", requestId="20261008T223000Z-00000000-0000-0000-0000-000000000001",
                       details={"url": "https://api.tutti.sh/v1/rooms", "method": "GET", "status": 500})
        downloaded = {**snapshot(logs, False, since=UNTIL - 85 * 60000),
                      "untilUnixMs": UNTIL - 25 * 60000,
                      "retention": "current-page-memory"}
        result = self.run_download(downloaded, extra=("--incident-at", "2026-10-08T22:30:00Z"))
        self.assertEqual(result["recordCount"], 1)
        request = json.loads((self.base / "web-logs.log").read_text().splitlines()[1])
        self.assertEqual(request["requestId"], "20261008T223000Z-00000000-0000-0000-0000-000000000001")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/web_requests.py"), "--web-logs",
                                 str(self.base / "web-logs.log"), "--incident-at", "2026-10-08T22:30:00Z"],
                                capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["failed_requests"][0]["request_ids"], ["20261008T223000Z-00000000-0000-0000-0000-000000000001"])


if __name__ == "__main__":
    unittest.main()
