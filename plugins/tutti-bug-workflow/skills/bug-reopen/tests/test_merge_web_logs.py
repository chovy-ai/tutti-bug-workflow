"""merge_web_logs.py on synthetic get_web_logs pages."""

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


def snapshot(records, truncated, next_before=None, account="user-a", since=SINCE):
    return {"pageSessionId": PAGE, "accountId": account, "sinceUnixMs": since, "untilUnixMs": UNTIL,
            "redacted": False, "records": records, "truncated": truncated,
            **({"nextBeforeSequence": next_before} if next_before is not None else {})}


class MergeWebLogsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def run_merge(self, *pages, expected=0):
        paths = []
        for index, page in enumerate(pages):
            path = self.base / f"page{index}.json"
            path.write_text(json.dumps(page))
            paths += ["--page", str(path)]
        result = subprocess.run([sys.executable, str(SCRIPT), "--connection-url", LINK, "--question-time", QUESTION,
                                 *paths, "--output", str(self.base / "web-logs.log")],
                                capture_output=True, text=True, timeout=20, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_pages_merge_in_time_order_with_metadata(self):
        first = {"message": json.dumps({"status": "Completed",
                                        "output": json.dumps(snapshot([record(3, 1000), record(2, 5000)], True, 2))})}
        second = snapshot([record(1, 9000)], False)
        result = self.run_merge(first, second)
        self.assertEqual((result["collectionStatus"], result["recordCount"], result["pages"]), ("complete", 3, 2))
        lines = (self.base / "web-logs.log").read_text().splitlines()
        self.assertEqual(json.loads(lines[0])["type"], "metadata")
        self.assertEqual([json.loads(line)["id"] for line in lines[1:]], [1, 2, 3])

    def test_stalled_cursor_keeps_records_as_partial(self):
        result = self.run_merge(snapshot([record(3, 1000)], True, 99))
        self.assertEqual((result["collectionStatus"], result["recordCount"]), ("partial", 1))

    def test_identity_window_and_status_errors_are_rejected(self):
        self.run_merge(snapshot([record(1, 1000)], False, account="user-b"), expected=2)
        self.run_merge(snapshot([record(1, 1000)], False, since=SINCE - 1), expected=2)
        self.run_merge(snapshot([record(1, 700000)], False), expected=2)
        self.run_merge({"status": "Error", "errorText": "denied"}, expected=2)


if __name__ == "__main__":
    unittest.main()
