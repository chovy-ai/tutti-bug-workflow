#!/usr/bin/env python3
"""Pull tutti-server logs for one bug report from AWS CloudWatch Logs Insights.

tutti-server access logs carry request_id but no user id, so the user's requests are
found by request ids within a window around question_time:

- given directly (`--request-id`, e.g. ones read from the Computer's desktopd.log), or
  found in the Web logs (`--web-logs`: web-logs.log or the exported diagnostics zip):
  current Tutti Web records the gateway's x-zk-request-id on every HTTP record
  (`requestId`, or `requestIds` for folded repeats);
- matched from the Web logs' HTTP records that carry no request id (older Web
  versions): the failed requests (or, without failures, the ones closest to
  question_time) are paired with the server access log of the same method, url_path and
  status nearest in time, and that access log's request_id is used;
- plus optional path fragments such as a room or Computer id.

All log lines of the resulting request ids are then pulled, not just the access lines.
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
from urllib.parse import urlparse
import zipfile

DEFAULT_GROUP = "/aws/containerinsights/nexight-ojo-us-east-1/application"
DEFAULT_REGION = "us-east-1"
BATCH = 20
LIMIT = 10000
SAFE = re.compile(r"[A-Za-z0-9._:\-/]{4,200}\Z")
REQUEST_ID = re.compile(r"\b\d{8}T\d{6}Z-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


def web_text(path):
    path = Path(path).expanduser()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return "\n".join(archive.read(name).decode("utf-8", "ignore") for name in archive.namelist()
                             if name.endswith((".jsonl", ".json", ".log")))
    return path.read_text(encoding="utf-8", errors="ignore")


def request_ids_from(path):
    """Collect tutti request ids (x-request-id / requestId) from web-logs.log or a diagnostics zip."""
    return list(dict.fromkeys(REQUEST_ID.findall(web_text(path))))


SERVER_PATH = re.compile(r"/v\d+/\S*")


def web_requests_from(path):
    """HTTP records the page sent to tutti-server, from web-logs.log or a diagnostics zip.

    Records that carry their own request id (`requestId`/`requestIds`) are marked
    `has_id`: their ids are used directly and they are not matched again. Older Tutti
    Web versions record none, so those are matched to server access logs instead.
    The server logs `url_path` without the `/api/<app>` prefix the page uses.
    """
    requests = []
    for line in web_text(path).splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("kind") != "http" or "desktopd" in str(record.get("source")):
            continue
        details = record.get("details") or {}
        url = urlparse(str(details.get("url") or ""))
        match = SERVER_PATH.search(url.path)
        if not match or (url.hostname or "").split(".")[0] in ("localhost", "127"):
            continue
        if isinstance(record.get("occurredAtUnixMs"), int):
            at = record["occurredAtUnixMs"]
        else:
            try:
                at = int(datetime.fromisoformat(str(record.get("at")).replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                continue
        status = details.get("status") if isinstance(details.get("status"), int) else None
        has_id = any(REQUEST_ID.search(json.dumps(value)) for value in (
            record.get("requestId"), record.get("requestIds"), details.get("requestId")) if value)
        requests.append({"at": at, "has_id": has_id, "method": str(details.get("method") or "GET").upper(), "path": match.group(0),
                         "status": status, "duration_ms": details.get("durationMs") or 0,
                         "failed": record.get("level") == "error" or status is None or status >= 400})
    return requests


def logfmt(value, key):
    match = re.search(rf"(?:^|\s){re.escape(key)}=(\S*)", value or "")
    return match.group(1) if match else None


def insights_ms(value):
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp() * 1000)


def correlate(anchors, rows, slack_ms):
    """Pair each Web request with the closest unused access log of the same method/path/status."""
    access = []
    for row in rows:
        log = row.get("log") or ""
        rid = logfmt(log, "request_id")
        if "log_type=api_access" not in log or not rid or not row.get("@timestamp"):
            continue
        status = logfmt(log, "status_code")
        access.append({"at": insights_ms(row["@timestamp"]), "rid": rid, "method": logfmt(log, "method"),
                       "path": logfmt(log, "url_path"), "status": int(status) if status and status.isdigit() else None})
    used, pairs = set(), []
    for anchor in anchors:
        window = anchor["duration_ms"] + slack_ms
        candidates = [entry for entry in access if entry["rid"] not in used and entry["path"] == anchor["path"]
                      and entry["method"] == anchor["method"]
                      and (anchor["status"] is None or entry["status"] == anchor["status"])
                      and abs(entry["at"] - anchor["at"]) <= window]
        if candidates:
            best = min(candidates, key=lambda entry: abs(entry["at"] - anchor["at"]))
            used.add(best["rid"])
            pairs.append((anchor, best["rid"]))
        else:
            pairs.append((anchor, None))
    return pairs


def pick_anchors(requests, moment_ms, since_ms, until_ms, limit):
    """Failed requests in the window first (closest to the incident), else the closest requests.

    Requests that already carry a request id need no matching and are left out.
    """
    inside = [request for request in requests
              if since_ms <= request["at"] <= until_ms and not request.get("has_id")]
    failed = [request for request in inside if request["failed"]]
    pool = failed or inside
    return sorted(pool, key=lambda request: abs(request["at"] - moment_ms))[:limit]


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


def access_query(container, paths):
    clauses = " or ".join(f"log like {json.dumps(f'url_path={path} ')}" for path in paths)
    return (f'fields @timestamp, kubernetes.namespace_name, kubernetes.pod_name, log '
            f'| filter kubernetes.container_name = "{container}" and log like "log_type=api_access" '
            f'and ({clauses}) | sort @timestamp asc | limit {LIMIT}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--question-time", required=True, help="ISO 8601 with timezone.")
    parser.add_argument("--request-id", action="append", default=[])
    parser.add_argument("--request-ids-file", help="One request id per line.")
    parser.add_argument("--web-logs", action="append", default=[],
                        help="web-logs.log or diagnostics zip: request ids, and HTTP records to match by path/time.")
    parser.add_argument("--path-contains", action="append", default=[], help="e.g. a room or Computer id.")
    parser.add_argument("--before-minutes", type=float, default=10)
    parser.add_argument("--after-minutes", type=float, default=10)
    parser.add_argument("--max-web-requests", type=int, default=40,
                        help="Web HTTP records to match to server access logs (failed ones first).")
    parser.add_argument("--match-slack-seconds", type=float, default=10,
                        help="Allowed clock/latency gap on top of the request duration when matching.")
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
        since = moment - timedelta(minutes=args.before_minutes)
        until = moment + timedelta(minutes=args.after_minutes)
        given = list(args.request_id)
        if args.request_ids_file:
            given += [line.strip() for line in Path(args.request_ids_file).read_text().splitlines() if line.strip()]
        web_ids, web_requests = [], []
        for web_logs in args.web_logs:
            web_ids += request_ids_from(web_logs)
            web_requests += web_requests_from(web_logs)
        known = list(dict.fromkeys(given + web_ids))
        anchors = [request for request in pick_anchors(web_requests, int(moment.timestamp() * 1000),
                                                       int(since.timestamp() * 1000), int(until.timestamp() * 1000),
                                                       args.max_web_requests)
                   if SAFE.fullmatch(request["path"])]
        if not known and not args.path_contains and not anchors:
            raise ValueError("No request ids or Web HTTP records in the window; give --web-logs, --request-id "
                             "or --path-contains.")
        bad = [term for term in known + args.path_contains if not SAFE.fullmatch(term)]
        if bad:
            raise ValueError(f"Unsafe search terms: {bad[:3]}")
        output = Path(args.output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2
    command = os.environ.get("AWS_CLI", "aws")
    result = {"question_time": args.question_time,
              "window": {"since": since.astimezone(timezone.utc).isoformat(), "until": until.astimezone(timezone.utc).isoformat()},
              "log_group": args.log_group, "region": args.region, "path_terms": args.path_contains}

    def collect():
        rows, truncated, pairs = [], False, []
        paths = list(dict.fromkeys(anchor["path"] for anchor in anchors))
        access = []
        for index in range(0, len(paths), BATCH):
            batch = run_query(command, args.region, args.log_group, since, until,
                              access_query(args.container, paths[index:index + BATCH]), args.poll_seconds)
            truncated = truncated or len(batch) >= LIMIT
            access += batch
        if anchors:
            pairs = correlate(anchors, access, int(args.match_slack_seconds * 1000))
        ids = list(dict.fromkeys(known + [rid for _, rid in pairs if rid]))
        terms = [f"request_id={rid}" for rid in ids] + list(dict.fromkeys(args.path_contains))
        for index in range(0, len(terms), BATCH):
            batch = run_query(command, args.region, args.log_group, since, until,
                              terms_query(args.container, terms[index:index + BATCH]), args.poll_seconds)
            truncated = truncated or len(batch) >= LIMIT
            rows += batch
        return rows, truncated, pairs, ids

    try:
        try:
            rows, truncated, pairs, ids = collect()
        except Blocked as blocked:
            if blocked.kind != "login_expired" or args.no_login:
                raise
            result["login"] = sso_login(command)
            if not result["login"]["ok"]:
                raise Blocked(f"AWS 登录已过期，自动登录没有完成：{result['login']['reason']}", "login_expired") from None
            rows, truncated, pairs, ids = collect()
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

    def web_request(anchor, rid=None):
        item = {"at": datetime.fromtimestamp(anchor["at"] / 1000, timezone.utc).isoformat(timespec="milliseconds"),
                "method": anchor["method"], "path": anchor["path"], "status": anchor["status"]}
        return {**item, "request_id": rid} if rid else item

    correlated = [web_request(anchor, rid) for anchor, rid in pairs if rid]
    metadata = {"type": "metadata", "source": "aws-cloudwatch-insights", **result,
                "request_ids": len(ids), "request_ids_given": len(given), "request_ids_in_web_logs": len(web_ids),
                "web_http_requests": len(web_requests),
                "web_requests_with_id": sum(1 for request in web_requests if request["has_id"]),
                "web_requests_matched": len(correlated),
                "web_requests_checked": len(pairs),
                "namespaces": namespaces, "environments": sorted({environment(n) for n in namespaces}),
                "matched_request_ids": len(matched), "record_count": len(records), "truncated": truncated,
                "correlated_requests": correlated}
    path = output / "server-logs.log"
    path.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in [metadata, *records]) + "\n",
                    encoding="utf-8")
    status = "empty" if not records else ("partial" if truncated else "captured")
    # Failed Web requests that never reached tutti-server (e.g. a gateway 429) are evidence too.
    unreached = [web_request(anchor) for anchor, rid in pairs if not rid and anchor["failed"]]
    print(json.dumps({**metadata, "status": status, "files": [str(path)],
                      "unmatched_request_ids": [rid for rid in ids if rid not in matched][:20],
                      "web_failures_not_in_server_logs": unreached[:20]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
