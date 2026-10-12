#!/usr/bin/env python3
"""Merge get_web_logs pages read through tutti-web call_tutti_tool into one web-logs.log.

The agent pages with input {"range": "10m", "limit": 200, "untilUnixMs": Q} and then
{"...", "beforeSequence": nextBeforeSequence} while truncated, saving each raw tool
result to a file. This script checks page/Account identity, the fixed window
[question_time - 10 min, question_time], sequence continuity and duplicates, then writes
JSON Lines (metadata first, records by occurrence time). Stateless; standard library only.
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
    """Accept the raw snapshot, an MCP content envelope, or the older chrome-devtools shapes."""
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


def merge(pages, page_id, account, question_time):
    until = int(datetime.fromisoformat(question_time.replace("Z", "+00:00")).timestamp() * 1000)
    since = until - WINDOW_MS
    records, seen, before, complete = [], set(), None, False
    for index, raw in enumerate(pages):
        snapshot = snapshot_of(raw)
        if snapshot.get("pageSessionId") != page_id or (account and snapshot.get("accountId") != account):
            raise ValueError(f"Page {index + 1} belongs to another page or Account.")
        account = account or snapshot.get("accountId")
        if snapshot.get("sinceUnixMs") != since or snapshot.get("untilUnixMs") != until:
            raise ValueError(f"Page {index + 1} was not read with untilUnixMs={until} and range 10m.")
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
        "type": "metadata", "source": "tutti-web-bridge", "pageSessionId": page_id,
        "accountId": account, "questionTime": question_time, "sinceUnixMs": since, "untilUnixMs": until,
        "pages": len(pages), "recordCount": len(records), "redacted": False,
        "collectionStatus": "complete" if complete else "partial",
        "earliestRecordUnixMs": records[0]["occurredAtUnixMs"] if records else None,
        "latestRecordUnixMs": records[-1]["occurredAtUnixMs"] if records else None,
        "recordTruncationCount": sum(1 for record in records if record.get("truncated") is True),
    }
    return metadata, records


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connection-url", required=True)
    parser.add_argument("--question-time", required=True, help="ISO 8601 with timezone.")
    parser.add_argument("--page", action="append", required=True, help="Saved tool result, in read order.")
    parser.add_argument("--output", required=True, help="Path ending in web-logs.log.")
    args = parser.parse_args()
    try:
        if not args.output.endswith("web-logs.log"):
            raise ValueError("--output must end with web-logs.log.")
        if datetime.fromisoformat(args.question_time.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("--question-time needs a timezone.")
        page_id, account = parse_link(args.connection_url)
        pages = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.page]
        metadata, records = merge(pages, page_id, account, args.question_time)
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
