#!/usr/bin/env python3
"""Validate a download_web_logs JSON file and write one web-logs.log.

The browser downloads the full snapshot; log bodies never pass through the agent's
tool responses. --download reads that local file and checks page/Account identity, the fixed window
[incident - 10 min, until], sequence continuity and duplicates, then writes
JSON Lines (metadata first, records by occurrence time). Stateless; standard library only.

until is --question-time (when the bug was reported), or 5 minutes after --incident-at
(when it happened) if that is earlier, so a late report still reads the failure itself.
Q and R must come from the same arguments; `--until-ms` prints untilUnixMs and range. --connection-url takes the WebMCP connection link,
or the bare page identity (web-diagnostics:<uuid>) when the page was found without a link;
then pass --account-id with the signed-in userId so the Account is still checked.
"""

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
import sys
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import emit  # noqa: E402

WINDOW_MS = 10 * 60 * 1000
AFTER_MS = 5 * 60 * 1000


def until_of(question_time, incident_at=None):
    moments = [datetime.fromisoformat(value.replace("Z", "+00:00")) for value in (question_time, incident_at) if value]
    if any(moment.tzinfo is None for moment in moments):
        raise ValueError("--question-time and --incident-at need a timezone.")
    until = int(moments[0].timestamp() * 1000)
    if len(moments) == 2:
        until = min(until, int(moments[1].timestamp() * 1000) + AFTER_MS)
    return until


def window_of(question_time, incident_at=None):
    until = until_of(question_time, incident_at)
    moment = datetime.fromisoformat((incident_at or question_time).replace("Z", "+00:00"))
    anchor = int(moment.timestamp() * 1000)
    since = anchor - WINDOW_MS
    # WebMCP offers preset ranges. Read a superset, then retain the incident window.
    range_name, span = ("10m", WINDOW_MS) if until - since <= WINDOW_MS else ("1h", 60 * 60 * 1000)
    return since, until, range_name, until - span


def parse_link(link):
    if link.startswith("web-diagnostics:"):
        return link, None
    url = urlparse(link)
    page = unquote(url.path.lstrip("/"))
    accounts = parse_qs(url.query).get("accountId", [])
    if url.scheme != "tutti-webmcp" or url.netloc != "page" or not page.startswith("web-diagnostics:") \
            or len(accounts) != 1:
        raise ValueError("Expected a tutti-webmcp://page/web-diagnostics:<uuid>?accountId=<id> link.")
    return page, accounts[0]


def prepare_download(snapshot, page_id, account, question_time, incident_at=None):
    since, until, range_name, read_since = window_of(question_time, incident_at)
    if snapshot.get("pageSessionId") != page_id or snapshot.get("accountId") != account:
        raise ValueError("The download belongs to another page or Account.")
    if snapshot.get("sinceUnixMs") != read_since or snapshot.get("untilUnixMs") != until:
        raise ValueError(f"Download has untilUnixMs={snapshot.get('untilUnixMs')}, "
                         f"sinceUnixMs={snapshot.get('sinceUnixMs')}; expected untilUnixMs={until} "
                         f"and sinceUnixMs={read_since} with range {range_name}. Use --until-ms "
                         "with the same question_time and incident_at, then download again.")
    records, previous_id = [], None
    for record in snapshot["records"]:
        rid = record.get("id")
        if (type(rid) is not int or rid < 1 or (previous_id is not None and rid >= previous_id)
                or not read_since <= record.get("occurredAtUnixMs", -1) <= until
                or record.get("pageSessionId") != page_id or record.get("userId") != account):
            raise ValueError("Download has a record out of window, sequence order or identity.")
        previous_id = rid
        if record["occurredAtUnixMs"] >= since:
            records.append(record)
    records.sort(key=lambda record: (record["occurredAtUnixMs"], record["id"]))
    metadata = {
        "type": "metadata", "source": "chrome-devtools-webmcp", "pageSessionId": page_id,
        "accountId": account, "questionTime": question_time, "incidentAt": incident_at,
        "sinceUnixMs": since, "untilUnixMs": until,
        "recordCount": len(records), "redacted": False, "collectionStatus": "complete",
        "earliestRecordUnixMs": records[0]["occurredAtUnixMs"] if records else None,
        "latestRecordUnixMs": records[-1]["occurredAtUnixMs"] if records else None,
        "recordTruncationCount": sum(1 for record in records if record.get("truncated") is True),
    }
    return metadata, records


def read_download(path, expected_size=None, expected_record_count=None):
    source = Path(path).expanduser()
    if source.suffix == ".crdownload":
        raise ValueError("The browser download is still in progress; use the completed JSON file.")
    contents = source.read_bytes()
    if expected_size is not None and len(contents) != expected_size:
        raise ValueError("Downloaded file size differs from sizeBytes; check the completed file.")
    snapshot = json.loads(contents.decode("utf-8"))
    if (not isinstance(snapshot, dict) or snapshot.get("redacted") is not False
            or snapshot.get("retention") != "current-page-memory"
            or snapshot.get("truncated") is not False
            or not isinstance(snapshot.get("records"), list)):
        raise ValueError("Expected a complete, unredacted download_web_logs snapshot.")
    if expected_record_count is not None and len(snapshot["records"]) != expected_record_count:
        raise ValueError("Downloaded record count differs from recordCount.")
    return snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connection-url", help="WebMCP connection link, or the page identity web-diagnostics:<uuid>.")
    parser.add_argument("--account-id", help="Signed-in userId; required with a bare page identity.")
    parser.add_argument("--question-time", required=True, help="ISO 8601 with timezone: when it was reported.")
    parser.add_argument("--incident-at", help="ISO 8601 with timezone: when it happened, if earlier.")
    parser.add_argument("--until-ms", action="store_true", help="Only print the fixed window for download_web_logs.")
    parser.add_argument("--download", help="Completed local JSON file from download_web_logs.")
    parser.add_argument("--expected-size", type=int, help="sizeBytes returned by download_web_logs.")
    parser.add_argument("--expected-record-count", type=int, help="recordCount returned by download_web_logs, before window filtering.")
    parser.add_argument("--output", help="Path ending in web-logs.log.")
    args = parser.parse_args()
    try:
        since, until, range_name, read_since = window_of(args.question_time, args.incident_at)
        if args.until_ms:
            emit({"ok": True, "questionTime": args.question_time, "incidentAt": args.incident_at,
                  "untilUnixMs": until, "range": range_name, "sinceUnixMs": since,
                  "readSinceUnixMs": read_since})
            return 0
        if not args.connection_url or not args.download or not args.output:
            raise ValueError("--connection-url, --download and --output are required.")
        if not args.output.endswith("web-logs.log"):
            raise ValueError("--output must end with web-logs.log.")
        if any(value is not None and (value < 0 or not args.download)
               for value in (args.expected_size, args.expected_record_count)):
            raise ValueError("Download expectations must be nonnegative and require --download.")
        page_id, account = parse_link(args.connection_url)
        if args.account_id:
            if account and account != args.account_id:
                raise ValueError("--account-id differs from the connection link's accountId.")
            account = args.account_id
        elif not account:
            raise ValueError("A bare page identity needs --account-id (the signed-in userId).")
        snapshot = read_download(args.download, args.expected_size, args.expected_record_count)
        metadata, records = prepare_download(snapshot, page_id, account, args.question_time, args.incident_at)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        emit({"ok": False, "error": str(error)})
        return 2
    text = "\n".join(json.dumps(item, ensure_ascii=False) for item in [metadata, *records]) + "\n"
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    emit({**metadata, "path": str(output), "sha256": hashlib.sha256(text.encode()).hexdigest()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
