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

    def test_expired_sso_login_is_renewed_then_retried(self):
        expired = {**self.env, "FAKE_AWS_EXPIRED": "1"}
        result = self.server("--request-id", RID1, env=expired)
        self.assertEqual((result["status"], result["login"]), ("captured", {"triggered": True, "ok": True}))
        (self.base / "aws.json").unlink()
        failed = self.server("--request-id", RID1, env={**expired, "FAKE_AWS_LOGIN": "fail"})
        self.assertEqual((failed["status"], failed["reason_kind"]), ("blocked", "login_expired"))
        self.assertIn("自动登录没有完成", failed["reason"])
        (self.base / "aws.json").unlink()
        unattended = self.server("--request-id", RID1, "--no-login", env=expired)
        self.assertEqual((unattended["status"], "login" in unattended), ("blocked", False))

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

    def test_web_requests_without_ids_are_matched_to_access_logs(self):
        # Tutti Web records requestId null; the page path /api/desktop/v2/... is url_path=/v2/... on the server.
        rid_ok = "20261010T094930Z-11111111-2222-3333-4444-555555555555"
        rid_fail = "20261010T094940Z-66666666-2222-3333-4444-555555555555"
        rid_other_time = "20261010T093000Z-77777777-2222-3333-4444-555555555555"
        path = "/v2/rooms/r1/agent-sessions/s1/prompt-queue"
        rows = [
            {"@timestamp": "2026-10-10 09:49:30.300", "kubernetes.namespace_name": "tutti", "kubernetes.pod_name": "p",
             "log": f"INFO request_id={rid_ok} log_type=api_access method=GET status_code=200 url_path={path} latency_ms=3"},
            {"@timestamp": "2026-10-10 09:49:40.400", "kubernetes.namespace_name": "tutti", "kubernetes.pod_name": "p",
             "log": f"INFO request_id={rid_fail} log_type=api_access method=POST status_code=500 url_path=/v2/rooms/r1/messages latency_ms=9"},
            {"@timestamp": "2026-10-10 09:49:40.500", "kubernetes.namespace_name": "tutti", "kubernetes.pod_name": "p",
             "log": f"ERROR request_id={rid_fail} message=send failed"},
            {"@timestamp": "2026-10-10 09:30:00.000", "kubernetes.namespace_name": "tutti", "kubernetes.pod_name": "p",
             "log": f"INFO request_id={rid_other_time} log_type=api_access method=POST status_code=500 url_path=/v2/rooms/r1/messages"},
        ]
        def http(at, method, url, status, level="info", source="web-http-transport"):
            return {"occurredAtUnixMs": at, "kind": "http", "level": level, "source": source, "requestId": None,
                    "details": {"method": method, "url": url, "status": status, "durationMs": 120}}
        base = 1791625770000  # 2026-10-10T09:49:30Z
        log = self.base / "web-logs.log"
        log.write_text("\n".join(json.dumps(item) for item in [
            {"type": "metadata"},
            http(base, "GET", f"https://tutti.sh/api/desktop{path}", 200),
            http(base + 10000, "POST", "https://tutti.sh/api/desktop/v2/rooms/r1/messages", 500, "error"),
            http(base + 20000, "GET", "https://tutti.sh/api/desktop/v2/agents/directory-projection?roomId=r1", 429, "error"),
            http(base, "GET", "/v1/computers/current/identity", 200, source="desktopd-http-transport"),
        ]) + "\n")
        env = {**self.env, "FAKE_AWS_ROWS": json.dumps(rows)}
        result = self.server("--web-logs", str(log), env=env)
        self.assertEqual(result["status"], "captured")
        self.assertEqual((result["request_ids_in_web_logs"], result["web_http_requests"]), (0, 3))
        # Only failures are matched when there are failures; the earlier 500 is outside the time slack.
        self.assertEqual([item["request_id"] for item in result["correlated_requests"]], [rid_fail])
        self.assertEqual(result["matched_request_ids"], 1)
        self.assertEqual([item["status"] for item in result["web_failures_not_in_server_logs"]], [429])
        logs = (self.base / "out/server-logs.log").read_text()
        self.assertIn("send failed", logs)  # application lines of the matched request come along
        self.assertNotIn(rid_other_time, logs)

        archive = self.base / "tutti-web-diagnostics.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("logs.jsonl", json.dumps({
                "at": "2026-10-10T09:49:30.000Z", "kind": "http", "level": "info", "source": "web-http-transport",
                "details": {"method": "GET", "url": f"https://tutti.sh/api/desktop{path}", "status": 200,
                            "durationMs": 50}}) + "\n")
        (self.base / "aws.json").unlink()
        from_zip = self.server("--web-logs", str(archive), env=env)
        self.assertEqual([item["request_id"] for item in from_zip["correlated_requests"]], [rid_ok])


if __name__ == "__main__":
    unittest.main()
