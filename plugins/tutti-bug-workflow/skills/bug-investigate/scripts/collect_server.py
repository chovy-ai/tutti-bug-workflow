#!/usr/bin/env python3
"""Pull tutti-server logs for one bug report from AWS CloudWatch Logs Insights.

tutti-server access logs carry request_id but no user id, so the user's requests are
found by the request ids in the Web logs (`--web-logs`: web-logs.log or the exported
diagnostics zip) or given directly, plus optional path fragments such as a room or
Computer id, within a window around question_time.
The Kubernetes namespace of the matches tells the environment: `tutti` is production,
`lane-ppe-*` is PPE, other `lane-*` are preview lanes.

An expired AWS SSO login is renewed on the spot: `aws sso login` opens the browser on
this machine, the person approves there, and the query is retried once. `--no-login`
turns that off (unattended runs).

Stateless: one JSON result on stdout and one server-logs.log (JSON Lines, metadata
first, records by time) in --output-dir. Exit 0 whenever a result is produced
(captured, empty or blocked); 2 for invalid input. Standard library only.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

DEFAULT_GROUP = "/aws/containerinsights/nexight-ojo-us-east-1/application"
DEFAULT_REGION = "us-east-1"
BATCH = 20
LIMIT = 10000
SAFE = re.compile(r"[A-Za-z0-9._:\-/]{4,200}\Z")
REQUEST_ID = re.compile(r"\b\d{8}T\d{6}Z-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def request_ids_from(path):
    """Collect tutti request ids (x-request-id / requestId) from web-logs.log or a diagnostics zip."""
    path = Path(path).expanduser()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            text = "\n".join(archive.read(name).decode("utf-8", "ignore") for name in archive.namelist()
                             if name.endswith((".jsonl", ".json", ".log")))
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
    return list(dict.fromkeys(REQUEST_ID.findall(text)))


EXPIRED = re.compile(r"expired|refresh failed|token does not exist|Error loading SSO Token|sso session", re.I)
LOGIN_TIMEOUT = 600


class Blocked(Exception):
    def __init__(self, message, kind="other"):
        super().__init__(message)
        self.kind = kind


def sso_login(command):
    """Run `aws sso login` (honours AWS_PROFILE); the CLI opens the browser itself."""
    try:
        result = subprocess.run([command, "sso", "login"], capture_output=True, text=True,
                                timeout=LOGIN_TIMEOUT, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"triggered": True, "ok": False, "reason": f"{LOGIN_TIMEOUT // 60} 分钟内没有完成浏览器授权"}
    if result.returncode:
        return {"triggered": True, "ok": False, "reason": (result.stderr or result.stdout).strip()[-300:]}
    return {"triggered": True, "ok": True}


def environment(namespace):
    if namespace == "tutti":
        return "生产"
    if namespace.startswith("lane-ppe"):
        return "PPE"
    if namespace.startswith("lane-"):
        return "预览环境"
    return "其他"


def aws(command, region, *arguments):
    try:
        result = subprocess.run([command, "--region", region, "--output", "json", *arguments],
                                capture_output=True, text=True, timeout=120, check=False)
    except FileNotFoundError:
        raise Blocked(f"aws CLI not found: {command}") from None
    except subprocess.TimeoutExpired:
        raise Blocked("aws CLI timed out") from None
    if result.returncode != 0:
        message = result.stderr.strip()[:400]
        raise Blocked(f"aws {arguments[1] if len(arguments) > 1 else ''} failed: {message}",
                      "login_expired" if EXPIRED.search(message) else "other")
    return json.loads(result.stdout or "{}")


def run_query(command, region, group, since, until, query, poll):
    started = aws(command, region, "logs", "start-query", "--log-group-name", group,
                  "--start-time", str(int(since.timestamp())), "--end-time", str(int(until.timestamp())),
                  "--query-string", query)
    query_id = started.get("queryId")
    if not query_id:
        raise Blocked("start-query returned no queryId")
    for _ in range(120):
        result = aws(command, region, "logs", "get-query-results", "--query-id", query_id)
        status = result.get("status")
        if status == "Complete":
            return [{item["field"]: item["value"] for item in row} for row in result.get("results", [])]
        if status in ("Failed", "Cancelled", "Timeout", "Unknown"):
            raise Blocked(f"CloudWatch query {status}")
        time.sleep(poll)
    raise Blocked("CloudWatch query did not finish in time")


def terms_query(container, terms):
    clauses = " or ".join(f"log like {json.dumps(term)}" for term in terms)
    return (f'fields @timestamp, kubernetes.namespace_name, kubernetes.pod_name, log '
            f'| filter kubernetes.container_name = "{container}" and ({clauses}) '
            f'| sort @timestamp asc | limit {LIMIT}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--question-time", required=True, help="ISO 8601 with timezone.")
    parser.add_argument("--request-id", action="append", default=[])
    parser.add_argument("--request-ids-file", help="One request id per line.")
    parser.add_argument("--web-logs", action="append", default=[], help="web-logs.log or diagnostics zip to read request ids from.")
    parser.add_argument("--path-contains", action="append", default=[], help="e.g. a room or Computer id.")
    parser.add_argument("--before-minutes", type=float, default=10)
    parser.add_argument("--after-minutes", type=float, default=10)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--log-group", default=DEFAULT_GROUP)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--container", default="tutti-server")
    parser.add_argument("--poll-seconds", type=float, default=2)
    parser.add_argument("--no-login", action="store_true", help="Do not renew an expired SSO login.")
    args = parser.parse_args()
    try:
        moment = datetime.fromisoformat(args.question_time.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("--question-time needs a timezone.")
        ids = list(args.request_id)
        if args.request_ids_file:
            ids += [line.strip() for line in Path(args.request_ids_file).read_text().splitlines() if line.strip()]
        for web_logs in args.web_logs:
            ids += request_ids_from(web_logs)
        ids = list(dict.fromkeys(ids))
        terms = [f"request_id={rid}" for rid in ids] + list(dict.fromkeys(args.path_contains))
        if not terms:
            raise ValueError("No request ids found; give --web-logs, --request-id or --path-contains.")
        bad = [term for term in ids + args.path_contains if not SAFE.fullmatch(term)]
        if bad:
            raise ValueError(f"Unsafe search terms: {bad[:3]}")
        output = Path(args.output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2
    since = moment - timedelta(minutes=args.before_minutes)
    until = moment + timedelta(minutes=args.after_minutes)
    command = os.environ.get("AWS_CLI", "aws")
    result = {"question_time": args.question_time,
              "window": {"since": since.astimezone(timezone.utc).isoformat(), "until": until.astimezone(timezone.utc).isoformat()},
              "log_group": args.log_group, "region": args.region, "request_ids": len(ids),
              "path_terms": args.path_contains}
    def collect():
        rows, truncated = [], False
        for index in range(0, len(terms), BATCH):
            batch = run_query(command, args.region, args.log_group, since, until,
                              terms_query(args.container, terms[index:index + BATCH]), args.poll_seconds)
            truncated = truncated or len(batch) >= LIMIT
            rows += batch
        return rows, truncated

    try:
        try:
            rows, truncated = collect()
        except Blocked as blocked:
            if blocked.kind != "login_expired" or args.no_login:
                raise
            result["login"] = sso_login(command)
            if not result["login"]["ok"]:
                raise Blocked(f"AWS 登录已过期，自动登录没有完成：{result['login']['reason']}", "login_expired") from None
            rows, truncated = collect()
    except Blocked as blocked:
        print(json.dumps({**result, "status": "blocked", "reason": str(blocked), "reason_kind": blocked.kind},
                         ensure_ascii=False))
        return 0
    seen, records = set(), []
    for row in sorted(rows, key=lambda r: r.get("@timestamp", "")):
        key = (row.get("@timestamp"), row.get("kubernetes.pod_name"), row.get("log"))
        if key in seen:
            continue
        seen.add(key)
        records.append({"ts": row.get("@timestamp"), "namespace": row.get("kubernetes.namespace_name"),
                        "pod": row.get("kubernetes.pod_name"), "log": row.get("log")})
    namespaces = sorted({r["namespace"] for r in records if r["namespace"]})
    matched = sorted({rid for rid in ids if any(f"request_id={rid}" in (r["log"] or "") for r in records)})
    metadata = {"type": "metadata", "source": "aws-cloudwatch-insights", **result,
                "namespaces": namespaces, "environments": sorted({environment(n) for n in namespaces}),
                "matched_request_ids": len(matched), "record_count": len(records), "truncated": truncated}
    path = output / "server-logs.log"
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in [metadata, *records]) + "\n",
                    encoding="utf-8")
    status = "empty" if not records else ("partial" if truncated else "captured")
    print(json.dumps({**metadata, "status": status, "files": [str(path)],
                      "unmatched_request_ids": [rid for rid in ids if rid not in matched][:20]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
