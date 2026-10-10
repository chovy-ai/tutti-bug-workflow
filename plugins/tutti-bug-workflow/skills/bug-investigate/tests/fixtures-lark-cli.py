#!/usr/bin/env python3
"""Fake lark-cli `base` shortcuts backed by a JSON file in FAKE_LARK_STATE."""

import json
import os
from pathlib import Path
import sys

state_path = Path(os.environ["FAKE_LARK_STATE"])
state = json.loads(state_path.read_text()) if state_path.exists() else {"records": {}, "next": 1, "calls": []}
args = sys.argv[1:]
if args[0] == "contact":
    users = json.loads(os.environ.get("FAKE_LARK_USERS", "[]"))
    def flag(name):
        return args[args.index(name) + 1] if name in args else None
    if flag("--user-ids") == "me":
        found = [users[0]]
    elif flag("--query"):
        found = [u for u in users if flag("--query") in u["localized_name"]]
    else:
        found = [u for u in users if u.get("has_chatted")]
    print(json.dumps({"ok": True, "data": {"users": found, "has_more": False}}))
    sys.exit(0)
assert args[0] == "base"
shortcut = args[1]


def values(flag):
    return [args[i + 1] for i, item in enumerate(args) if item == flag]


def value(flag):
    found = values(flag)
    return found[0] if found else None


def reply(data, ok=True, code=0):
    state_path.write_text(json.dumps(state))
    print(json.dumps({"ok": ok, "data": data} if ok else {"ok": False, "error": {"message": data}}))
    sys.exit(code)


state["calls"].append(shortcut)
fail = os.environ.get("FAKE_LARK_FAIL")
if fail == shortcut:
    reply("simulated failure", ok=False, code=1)
records = state["records"]
if shortcut == "+record-upsert":
    fields = json.loads(value("--json"))
    record_id = value("--record-id")
    if record_id:
        records[record_id].update(fields)
    else:
        record_id = f"rec{state['next']}"
        state["next"] += 1
        records[record_id] = fields
        if os.environ.get("FAKE_LARK_CRASH_AFTER_CREATE"):
            state_path.write_text(json.dumps(state))
            sys.exit(1)
    reply({"record": {"record_id": record_id}, "created": not value("--record-id")})
if shortcut == "+record-get":
    record_id = value("--record-id")
    record = records[record_id]
    ids = [item for item in values("--field-id") if record.get(item) not in (None, "", [])]
    reply({"record_id_list": [record_id], "field_id_list": ids, "data": [[record[item] for item in ids]]})
if shortcut == "+record-list":
    field, _, expected = json.loads(value("--filter-json"))["conditions"][0]
    reply({"record_id_list": [rid for rid, rec in records.items() if rec.get(field) == expected]})
if shortcut == "+record-upload-attachment":
    record = records[value("--record-id")]
    cell = record.setdefault(value("--field-id"), [])
    for path in values("--file"):
        state["next"] += 1
        cell.append({"file_token": f"tok{state['next']}", "name": Path(path).name,
                     "size": Path(path).stat().st_size})
    reply({})
if shortcut == "+record-download-attachment":
    token = value("--file-token")
    item = next(i for i in records[value("--record-id")].get(os.environ.get("FAKE_LARK_ATTACH_FIELD", "fldEOh3AxT"), [])
                if i["file_token"] == token)
    Path(value("--output")).write_bytes(b"x" * item["size"])
    reply({"saved": value("--output")})
reply(f"unsupported {shortcut}", ok=False, code=1)
