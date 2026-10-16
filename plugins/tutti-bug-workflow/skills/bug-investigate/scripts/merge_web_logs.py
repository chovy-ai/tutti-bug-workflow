#!/usr/bin/env python3
"""Merge get_web_logs pages read through chrome-devtools execute_webmcp_tool into one web-logs.log.

The agent pages with input {"range": "10m", "limit": 200, "untilUnixMs": Q} and then
{"...", "beforeSequence": nextBeforeSequence} while truncated, saving each raw tool
result to a file. This script checks page/Account identity, the fixed window
[until - 10 min, until], sequence continuity and duplicates, then writes
JSON Lines (metadata first, records by occurrence time). Stateless; standard library only.

until is --question-time (when the bug was reported), or 5 minutes after --incident-at
(when it happened) if that is earlier, so a late report still reads the failure itself.
Q must be computed from the same arguments, to the millisecond; `--until-ms` prints it. --connection-url takes the WebMCP connection link,
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


def snapshot_of(raw):
    """Accept the tool result in the shapes chrome-devtools-mcp may return."""
    value = raw
    for _ in range(8):  # message -> JSON -> status/output -> JSON -> snapshot, plus envelopes
        if isinstance(value, str):
            value = json.loads(value)
            continue
        if isinstance(value, dict) and "records" in value:
            return value
        if isinstance(value, dict) and "structuredContent" in value:
            value = value["structuredContent"]
        elif isinstance(value, dict) and "message" in value:
            value = value["message"]
        elif isinstance(value, dict) and "status" in value:
            if value["status"] != "Completed" or value.get("errorText"):
                raise ValueError(f"WebMCP execution {value.get('status')}: {value.get('errorText')}")
            value = value.get("output")
        elif isinstance(value, dict) and isinstance(value.get("content"), list):
            value = next(item["text"] for item in value["content"] if item.get("type") == "text")
        else:
            break
    raise ValueError("Not a get_web_logs snapshot.")


def merge(pages, page_id, account, question_time, incident_at=None):
    until = until_of(question_time, incident_at)
    since = until - WINDOW_MS
    records, seen, before, complete = [], set(), None, False
    for index, raw in enumerate(pages):
        snapshot = snapshot_of(raw)
        if snapshot.get("pageSessionId") != page_id or (account and snapshot.get("accountId") != account):
            raise ValueError(f"Page {index + 1} belongs to another page or Account.")
        account = account or snapshot.get("accountId")
        if snapshot.get("sinceUnixMs") != since or snapshot.get("untilUnixMs") != until:
            raise ValueError(f"Page {index + 1} was read with untilUnixMs={snapshot.get('untilUnixMs')}, "
                             f"sinceUnixMs={snapshot.get('sinceUnixMs')}; --question-time/--incident-at give untilUnixMs={until} "
                             "with range 10m. Read every page with the untilUnixMs printed by --until-ms for the same "
                             "question_time and incident_at.")
        for record in snapshot["records"]:
            rid = record.get("id")
            if (not isinstance(rid, int) or rid in seen or (before is not None and rid >= before)
                    or not since <= record.get("occurredAtUnixMs", -1) <= until
                    or record.get("pageSessionId") != page_id or record.get("userId") != account):
                raise ValueError(f"Page {index + 1} has a record out of window, order or identity.")
            seen.add(rid)
            records.append(record)
        if not snapshot.get("truncated"):
            complete = index == len(pages) - 1
            if not complete:
                raise ValueError("Pages continue after an untruncated page.")
            break
        before = snapshot.get("nextBeforeSequence")
        if not snapshot["records"] or before != snapshot["records"][-1]["id"]:
            break  # Stalled cursor: keep what was read, mark partial.
    records.sort(key=lambda record: (record["occurredAtUnixMs"], record["id"]))
    metadata = {
        "type": "metadata", "source": "chrome-devtools-webmcp", "pageSessionId": page_id,
        "accountId": account, "questionTime": question_time, "incidentAt": incident_at,
        "sinceUnixMs": since, "untilUnixMs": until,
        "pages": len(pages), "recordCount": len(records), "redacted": False,
        "collectionStatus": "complete" if complete else "partial",
        "earliestRecordUnixMs": records[0]["occurredAtUnixMs"] if records else None,
        "latestRecordUnixMs": records[-1]["occurredAtUnixMs"] if records else None,
        "recordTruncationCount": sum(1 for record in records if record.get("truncated") is True),
    }
    return metadata, records


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connection-url", help="WebMCP connection link, or the page identity web-diagnostics:<uuid>.")
    parser.add_argument("--account-id", help="Signed-in userId; required with a bare page identity.")
    parser.add_argument("--question-time", required=True, help="ISO 8601 with timezone: when it was reported.")
    parser.add_argument("--incident-at", help="ISO 8601 with timezone: when it happened, if earlier.")
    parser.add_argument("--until-ms", action="store_true", help="Only print the untilUnixMs to read pages with.")
    parser.add_argument("--page", action="append", help="Saved tool result, in read order.")
    parser.add_argument("--output", help="Path ending in web-logs.log.")
    args = parser.parse_args()
    try:
        until = until_of(args.question_time, args.incident_at)
        if args.until_ms:
            emit({"ok": True, "questionTime": args.question_time, "incidentAt": args.incident_at,
                  "untilUnixMs": until})
            return 0
        if not args.connection_url or not args.page or not args.output:
            raise ValueError("--connection-url, --page and --output are required to merge.")
        if not args.output.endswith("web-logs.log"):
            raise ValueError("--output must end with web-logs.log.")
        page_id, account = parse_link(args.connection_url)
        if args.account_id:
            if account and account != args.account_id:
                raise ValueError("--account-id differs from the connection link's accountId.")
            account = args.account_id
        elif not account:
            raise ValueError("A bare page identity needs --account-id (the signed-in userId).")
        pages = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.page]
        metadata, records = merge(pages, page_id, account, args.question_time, args.incident_at)
    except (ValueError, OSError, KeyError, StopIteration) as error:
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
