#!/usr/bin/env python3
"""List the page's tutti-server requests and their request ids for the 排查线索 file.

Reads web-logs.log or the exported diagnostics zip. Current Tutti Web records the
gateway's x-zk-request-id on every HTTP record (`requestId`, or `requestIds` for folded
repeats), so RD can look the server logs up later; nothing is queried here.

Output: one JSON result with the failed requests (time, method, path, status, request
ids), the requests closest to --question-time when nothing failed, and how many HTTP
records carry no id (older Web versions). Exit 2 for invalid input. Standard library only.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import emit  # noqa: E402

REQUEST_ID = re.compile(r"\b\d{8}T\d{6}Z-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
SERVER_PATH = re.compile(r"/v\d+/\S*")
NEAREST = 10


def web_text(path):
    path = Path(path).expanduser()
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return "\n".join(archive.read(name).decode("utf-8", "ignore") for name in archive.namelist()
                             if name.endswith((".jsonl", ".json", ".log")))
    return path.read_text(encoding="utf-8", errors="ignore")


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def web_requests(path):
    """HTTP records the page sent to tutti-server; local desktopd calls are skipped."""
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
        ids = list(dict.fromkeys(REQUEST_ID.findall(json.dumps(
            [record.get("requestId"), record.get("requestIds"), details.get("requestId")]))))
        requests.append({"at_ms": at, "at": iso(at), "method": str(details.get("method") or "GET").upper(),
                         "path": match.group(0), "status": status, "request_ids": ids,
                         "failed": record.get("level") == "error" or status is None or status >= 400})
    return sorted(requests, key=lambda item: item["at_ms"])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--web-logs", required=True, help="web-logs.log or tutti-web-diagnostics-*.zip")
    parser.add_argument("--question-time", help="ISO 8601 with timezone; picks the nearest requests.")
    args = parser.parse_args()
    try:
        requests = web_requests(args.web_logs)
        moment = None
        if args.question_time:
            moment = datetime.fromisoformat(args.question_time.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                raise ValueError("--question-time needs a timezone.")
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        emit({"ok": False, "error": str(error)})
        return 2
    failed = [item for item in requests if item["failed"]]
    nearest = []
    if not failed and moment:
        ms = moment.timestamp() * 1000
        nearest = sorted(sorted(requests, key=lambda item: abs(item["at_ms"] - ms))[:NEAREST],
                         key=lambda item: item["at_ms"])
    strip = lambda items: [{k: v for k, v in item.items() if k not in ("at_ms", "failed")} for item in items]
    emit({"ok": True, "http_requests": len(requests),
          "with_request_id": sum(1 for item in requests if item["request_ids"]),
          "without_request_id": sum(1 for item in requests if not item["request_ids"]),
          "failed_requests": strip(failed), "nearest_requests": strip(nearest)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
