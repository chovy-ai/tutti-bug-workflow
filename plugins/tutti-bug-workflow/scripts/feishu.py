#!/usr/bin/env python3
"""Feishu Bug record operations for the QA bug-report flow, via lark-cli; standard library only.

Stateless: nothing is persisted locally. The agent keeps record_id in its session
context and passes it on every call; the Feishu record itself is the source of
truth for field values and attachments. This script owns field mapping,
append/overwrite rules, attachment de-duplication and read-back verification.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workbench as wb  # noqa: E402

# Fields this flow may write. Append keeps human and earlier-run content.
OVERWRITE = {"title", "description", "analysis_conclusion", "analysis_report",
             "investigation_evidence", "code_baselines", "code_references",
             "suspected_modules", "ui_only", "workflow_status"}
APPEND = {"logs", "dialogue", "open_items"}
ATTACHMENT_FIELDS = {"attachments"}


class LarkError(ValueError):
    pass


class Feishu:
    def __init__(self, cfg):
        feishu = cfg.get("feishu") or {}
        self.base = feishu.get("base_token")
        self.table = feishu.get("table_id")
        self.identity = feishu.get("identity") or "user"
        self.fields = feishu.get("field_map") or {}
        self.status_values = (feishu.get("workflow") or {}).get("status_values") or {}
        if not self.base or not self.table or not self.fields:
            raise ValueError("Config needs feishu.base_token, table_id and field_map.")
        command = os.environ.get("LARK_CLI")
        if not command:
            command = next((item["command"] for item in cfg.get("cli_dependencies", [])
                            if item.get("name") == "lark-cli"), "lark-cli")
        self.command = command

    def field_id(self, key):
        value = self.fields.get(key)
        if not value:
            raise ValueError(f"field_map has no entry for {key!r}.")
        return value

    def run(self, shortcut, *arguments):
        command = [self.command, "base", shortcut, "--base-token", self.base,
                   "--table-id", self.table, "--as", self.identity, *arguments]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        except FileNotFoundError:
            raise LarkError(f"lark-cli not found: {self.command}") from None
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise LarkError(f"lark-cli {shortcut} returned non-JSON (exit {result.returncode}): "
                            f"{(result.stderr or result.stdout).strip()[:500]}") from None
        if result.returncode != 0 or value.get("ok") is not True:
            error = value.get("error") or {}
            raise LarkError(f"lark-cli {shortcut} failed: {error.get('message') or value}")
        return value.get("data") or {}

    def read(self, record_id, keys):
        arguments = ["--record-id", record_id, "--format", "json"]
        for key in keys:
            arguments += ["--field-id", self.field_id(key)]
        data = self.run("+record-get", *arguments)
        if data.get("record_id_list") != [record_id] or len(data.get("data") or []) != 1:
            raise LarkError(f"Record {record_id} was not returned.")
        # Empty cells are omitted from field_id_list, so map by returned IDs.
        row = dict(zip(data.get("field_id_list") or [], data["data"][0]))
        return {key: row.get(self.field_id(key)) for key in keys}

    def find_by_title(self, title):
        condition = {"logic": "and", "conditions": [[self.field_id("title"), "==", title]]}
        data = self.run("+record-list", "--format", "json", "--limit", "10",
                        "--field-id", self.field_id("title"),
                        "--filter-json", json.dumps(condition, ensure_ascii=False))
        return data.get("record_id_list") or []

    def upsert(self, values, record_id=None):
        arguments = ["--json", json.dumps(values, ensure_ascii=False)]
        if record_id:
            arguments += ["--record-id", record_id]
        data = self.run("+record-upsert", *arguments)
        record = data.get("record") or {}
        return record.get("record_id") or record.get("id") or data.get("record_id")


def text_value(raw):
    if raw.startswith("@"):
        return Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    return raw


def parse_assignments(items, allowed, mode):
    result = {}
    for item in items or []:
        key, separator, raw = item.partition("=")
        if not separator:
            raise ValueError(f"--{mode} expects key=value or key=@file, got {item!r}.")
        if key not in allowed:
            raise ValueError(f"{key!r} cannot be written with --{mode}; allowed: {sorted(allowed)}.")
        if key in result:
            raise ValueError(f"{key!r} given twice.")
        result[key] = text_value(raw)
    return result


def create(args, client):
    # Look up by exact title first so a retried or interrupted create never duplicates.
    matches = client.find_by_title(args.title)
    if len(matches) > 1:
        raise ValueError(f"Several records titled {args.title!r}: {matches}; pass the right one "
                         "as --record-id to later commands.")
    if matches:
        wb.emit({"action": "existing", "record_id": matches[0]})
        return
    values = {client.field_id("title"): args.title,
              client.field_id("description"): text_value(args.description)}
    stage = client.status_values.get("bug")
    if stage and "workflow_status" in client.fields:
        values[client.field_id("workflow_status")] = stage
    record_id = client.upsert(values)
    if not record_id:
        matches = client.find_by_title(args.title)
        if len(matches) != 1:
            raise LarkError("Create returned no record_id and the title lookup was not unique.")
        record_id = matches[0]
    wb.emit({"action": "created", "record_id": record_id})


def read(args, client):
    keys = args.field or sorted(client.fields)
    wb.emit({"record_id": args.record_id, "fields": client.read(args.record_id, keys)})


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def write(args, client):
    record_id = args.record_id
    overwrite = parse_assignments(args.set, OVERWRITE, "set")
    append = parse_assignments(args.append, APPEND, "append")
    if not overwrite and not append:
        raise ValueError("Nothing to write; use --set or --append.")
    current = client.read(record_id, sorted(append)) if append else {}
    expected = dict(overwrite)
    skipped = []
    for key, addition in append.items():
        existing = as_text(current.get(key)).rstrip()
        if addition.strip() and addition.strip() in existing:
            skipped.append(key)  # Retried append; already present.
            continue
        expected[key] = f"{existing}\n\n{addition}" if existing else addition
    if expected:
        client.upsert({client.field_id(key): value for key, value in expected.items()}, record_id)
        actual = client.read(record_id, sorted(expected))
        mismatched = [key for key, value in expected.items()
                      if as_text(actual.get(key)).strip() != value.strip()]
        if mismatched:
            raise LarkError(f"Read-back differs for {mismatched}; another edit may have raced, re-run.")
    wb.emit({"record_id": record_id, "written": sorted(expected), "already_present": skipped,
             "verified": True})


def attach(args, client):
    record_id = args.record_id
    if args.field not in ATTACHMENT_FIELDS:
        raise ValueError(f"Attachment field must be one of {sorted(ATTACHMENT_FIELDS)}.")
    files = []
    for raw in args.file:
        file = Path(raw).expanduser().resolve()
        if not file.is_file():
            raise ValueError(f"Not a file: {file}")
        files.append((file, file.stat().st_size))
    if len({file.name for file, _ in files}) != len(files):
        raise ValueError("Files uploaded together need distinct names for read-back matching.")
    existing = client.read(record_id, [args.field])[args.field] or []
    # The record is the source of truth: a file with the same name and size is already attached.
    attached = {(item.get("name"), item.get("size")): item for item in existing}
    pending = [(file, size) for file, size in files if (file.name, size) not in attached]
    uploaded = []
    if pending:
        arguments = ["--record-id", record_id, "--field-id", client.field_id(args.field)]
        for file, _ in pending:
            arguments += ["--file", str(file)]
        client.run("+record-upload-attachment", *arguments)
        present = {item.get("file_token") for item in existing}
        after = client.read(record_id, [args.field])[args.field] or []
        added = [item for item in after if item.get("file_token") not in present]
        for file, size in pending:
            match = [item for item in added if item.get("name") == file.name and item.get("size") == size]
            if len(match) != 1:
                raise LarkError(f"Uploaded {file.name} was not found exactly once on read-back.")
            uploaded.append({"name": file.name, "size": size, "file_token": match[0]["file_token"]})
    wb.emit({"record_id": record_id, "uploaded": uploaded, "verified": True,
             "already_attached": [{"name": file.name, "size": size,
                                   "file_token": attached[(file.name, size)].get("file_token")}
                                  for file, size in files if (file.name, size) in attached]})


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    for name in ("create", "read", "write", "attach"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name != "create":
            command.add_argument("--record-id", required=True)
        if name == "create":
            command.add_argument("--title", required=True)
            command.add_argument("--description", required=True, help="Text, or @file.")
        if name == "read":
            command.add_argument("--field", action="append", help="field_map key; repeatable.")
        if name == "write":
            command.add_argument("--set", action="append", help="key=text or key=@file; overwrites.")
            command.add_argument("--append", action="append", help="key=text or key=@file; appends.")
        if name == "attach":
            command.add_argument("--file", action="append", required=True)
            command.add_argument("--field", default="attachments")
    return result


def main():
    args = parser().parse_args()
    try:
        root = wb.data_root(args)
        client = Feishu(wb.load_config(args, root))
        {"create": create, "read": read, "write": write, "attach": attach}[args.operation](args, client)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
