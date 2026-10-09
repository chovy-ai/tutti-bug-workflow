#!/usr/bin/env python3
"""Report the current Web and Computer log collection state for one Feishu Bug record.

Stateless and non-blocking: it only reports. Each source gets its status (or
not_attempted when no result was given) and, for every collected file, whether a
file with the same name and size is attached to the record right now.

--web accepts the collect_web_logs result; --computer accepts collect_computer.py
output. Either may also be a plain {"status": ..., "reason": ...} object, e.g. for a
pending device choice. Values are inline JSON or @file.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feishu  # noqa: E402
import workbench as wb  # noqa: E402


def load(raw):
    if raw is None:
        return None
    text = Path(raw[1:]).expanduser().read_text(encoding="utf-8") if raw.startswith("@") else raw
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("Collection results must be JSON objects.")
    return value


def web_state(result):
    if "collectionStatus" in result:  # collect_web_logs metadata
        status = "partial" if result["collectionStatus"] == "partial" else (
            "empty" if result.get("recordCount") == 0 else "captured")
        files = [result["outputPath"]] if result.get("outputPath") else []
        return status, result.get("incompleteReason"), files
    return result.get("status", "unknown"), result.get("reason"), result.get("files", [])


def computer_state(result):
    files = [item["path"] if isinstance(item, dict) else item for item in result.get("files", [])]
    return result.get("status", "unknown"), result.get("reason"), files


def report(result, parse, attachments):
    if result is None:
        return {"status": "not_attempted"}
    status, reason, paths = parse(result)
    files = []
    for raw in paths:
        path = Path(raw)
        size = path.stat().st_size if path.is_file() else None
        files.append({"name": path.name, "size": size, "local": size is not None,
                      "attached": (path.name, size) in attachments})
    entry = {"status": status, "files": files}
    if reason:
        entry["reason"] = reason
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--record-id", required=True)
    parser.add_argument("--web")
    parser.add_argument("--computer")
    parser.add_argument("--data-dir")
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        web, computer = load(args.web), load(args.computer)
        client = feishu.Feishu(wb.load_config(args, wb.data_root(args)))
        existing = client.read(args.record_id, ["attachments"])["attachments"] or []
    except (ValueError, OSError) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    attachments = {(item.get("name"), item.get("size")) for item in existing}
    wb.emit({"record_id": args.record_id,
             "web": report(web, web_state, attachments),
             "computer": report(computer, computer_state, attachments)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
