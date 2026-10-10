#!/usr/bin/env python3
"""Feishu Bug record operations for the QA bug-report flow, via lark-cli; standard library only.

Stateless: nothing is persisted locally. The agent keeps record_id in its session
context and passes it on every call; the Feishu record itself is the source of
truth. Records go to the `bug_report` table in the data-directory config (falling
back to the plugin's example config). This script owns field mapping, select-option
validation, date conversion, the agent-owned root-cause block, attachment
de-duplication, person lookup and read-back verification.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as wb  # noqa: E402

# Fields the agent may set with --set. Person fields use `assign`; attachments use `attach`.
SETTABLE = {"title", "platform", "priority", "module", "issue_type", "record_time", "root_cause"}
SELECTS = {"status", "platform", "priority", "issue_type", "module"}
ATTACHMENT_FIELDS = {"attachments"}
ROOT_CAUSE_MARK = "【Agent 分析根因】"


class LarkError(ValueError):
    pass


def bug_report_config(cfg):
    section = cfg.get("bug_report")
    if not section:
        example = wb.read_json(wb.PLUGIN_ROOT / "config/workbench.example.json")
        section = example.get("bug_report") or {}
    return section


class Feishu:
    def __init__(self, cfg):
        table = bug_report_config(cfg)
        self.base = table.get("base_token")
        self.table = table.get("table_id")
        self.view = table.get("view_id")
        self.identity = table.get("identity") or "user"
        self.timezone = ZoneInfo(table.get("timezone") or "Asia/Shanghai")
        self.fields = {key: value for key, value in (table.get("field_map") or {}).items() if value}
        self.defaults = table.get("defaults") or {}
        self.platforms = table.get("platform_choices") or []
        self.excluded_priorities = table.get("excluded_priorities") or []
        if not self.base or not self.table or "title" not in self.fields:
            raise ValueError("Config needs bug_report.base_token, table_id and field_map.title.")
        command = os.environ.get("LARK_CLI")
        if not command:
            command = next((item["command"] for item in cfg.get("cli_dependencies", [])
                            if item.get("name") == "lark-cli"), "lark-cli")
        self.command = command
        self._options = {}

    def field_id(self, key):
        value = self.fields.get(key)
        if not value:
            raise ValueError(f"bug_report.field_map has no entry for {key!r}.")
        return value

    def configured(self, key):
        return bool(self.fields.get(key))

    def _invoke(self, command, label):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
        except FileNotFoundError:
            raise LarkError(f"lark-cli not found: {self.command}") from None
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise LarkError(f"lark-cli {label} returned non-JSON (exit {result.returncode}): "
                            f"{(result.stderr or result.stdout).strip()[:500]}") from None
        if result.returncode != 0 or value.get("ok") is not True:
            error = value.get("error") or {}
            raise LarkError(f"lark-cli {label} failed: {error.get('message') or value}")
        return value.get("data") or {}

    def run(self, shortcut, *arguments):
        return self._invoke([self.command, "base", shortcut, "--base-token", self.base,
                             "--table-id", self.table, "--as", self.identity, *arguments], shortcut)

    def contact(self, *arguments):
        data = self._invoke([self.command, "contact", "+search-user", "--as", "user", "--format", "json",
                             "--exclude-external-users", *arguments], "contact +search-user")
        return [{"open_id": user.get("open_id"), "name": user.get("localized_name"),
                 "department": user.get("department") or None,
                 "email": user.get("email") or user.get("enterprise_email") or None}
                for user in data.get("users") or [] if user.get("open_id")]

    def options(self, key):
        if key not in self._options:
            data = self.run("+field-get", "--field-id", self.field_id(key), "--format", "json")
            field = data.get("field", data)
            prop = field.get("property") or field.get("options") or {}
            items = prop.get("options") if isinstance(prop, dict) else prop
            self._options[key] = [item.get("name") for item in items or [] if item.get("name")]
        return self._options[key]

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

    def me(self):
        users = self.contact("--user-ids", "me")
        if len(users) != 1:
            raise LarkError("Could not resolve the logged-in lark-cli user for 提交人.")
        return users[0]

    def cell(self, key, value):
        """Validate and convert one agent-provided value into a Base CellValue."""
        if key in SELECTS:
            choices = self.options(key)
            if value not in choices:
                raise ValueError(f"{value!r} is not an option of {key}; choose one of: {choices}")
            if key == "platform" and self.platforms and value not in self.platforms:
                raise ValueError(f"所属端 must be one of {self.platforms} for this view.")
            return value
        if key == "record_time":
            text = value.strip()
            moment = (datetime.fromisoformat(text.replace("Z", "+00:00")) if "T" in text or "+" in text
                      else datetime.fromisoformat(text + "T00:00:00").replace(tzinfo=self.timezone))
            if moment.tzinfo is None:
                raise ValueError("record_time needs a timezone or a plain date.")
            return moment.astimezone(self.timezone).strftime("%Y-%m-%d %H:%M:%S")
        return value


def text_value(raw):
    if raw.startswith("@"):
        return Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    return raw


def parse_assignments(items):
    result = {}
    for item in items or []:
        key, separator, raw = item.partition("=")
        if not separator:
            raise ValueError(f"--set expects key=value or key=@file, got {item!r}.")
        if key not in SETTABLE:
            raise ValueError(f"{key!r} cannot be written with --set; allowed: {sorted(SETTABLE)}.")
        if key in result:
            raise ValueError(f"{key!r} given twice.")
        result[key] = text_value(raw).strip()
    return result


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    return json.dumps(value, ensure_ascii=False)


def merge_root_cause(existing, content):
    """Replace only the agent-owned block; keep anything people wrote."""
    existing = as_text(existing).rstrip()
    block = f"{ROOT_CAUSE_MARK}\n{content}"
    if ROOT_CAUSE_MARK in existing:
        return existing[:existing.index(ROOT_CAUSE_MARK)].rstrip() + ("\n\n" if existing.split(ROOT_CAUSE_MARK)[0].strip() else "") + block
    return f"{existing}\n\n{block}" if existing else block


def matches(key, expected, actual):
    if key == "record_time":
        return bool(actual) and str(actual)[:10] == expected[:10]
    if key in SELECTS:
        values = actual if isinstance(actual, list) else [actual]
        return expected in values
    return as_text(actual).strip() == expected.strip()


def write_values(client, record_id, values):
    """Write converted values, then read back and compare."""
    cells = {key: client.cell(key, value) for key, value in values.items()}
    if "root_cause" in cells:
        current = client.read(record_id, ["root_cause"])["root_cause"]
        cells["root_cause"] = merge_root_cause(current, cells["root_cause"])
    client.upsert({client.field_id(key): value for key, value in cells.items()}, record_id)
    actual = client.read(record_id, sorted(cells))
    mismatched = [key for key, value in cells.items() if not matches(key, value, actual.get(key))]
    if mismatched:
        raise LarkError(f"Read-back differs for {mismatched}; another edit may have raced, re-run.")
    notes = []
    if values.get("priority") in client.excluded_priorities:
        notes.append(f"优先级 {values['priority']} 的记录不会出现在视图 {client.view} 中")
    return sorted(cells), notes


def create(args, client):
    # Look up by exact title first so a retried or interrupted create never duplicates.
    found = client.find_by_title(args.title)
    if len(found) > 1:
        raise ValueError(f"Several records titled {args.title!r}: {found}; pass the right one "
                         "as --record-id to later commands.")
    if found:
        wb.emit({"action": "existing", "record_id": found[0]})
        return
    extra = parse_assignments(args.set)
    extra.pop("title", None)
    values = {client.field_id("title"): args.title}
    for key, value in client.defaults.items():
        if client.configured(key):
            values[client.field_id(key)] = client.cell(key, value)
    if client.configured("reporter"):
        values[client.field_id("reporter")] = [{"id": client.me()["open_id"]}]
    if client.configured("record_time"):
        values[client.field_id("record_time")] = client.cell(
            "record_time", args.record_time or datetime.now(client.timezone).isoformat())
    record_id = client.upsert(values)
    if not record_id:
        found = client.find_by_title(args.title)
        if len(found) != 1:
            raise LarkError("Create returned no record_id and the title lookup was not unique.")
        record_id = found[0]
    written, notes = write_values(client, record_id, extra) if extra else ([], [])
    wb.emit({"action": "created", "record_id": record_id, "written": written, "notes": notes})


def read(args, client):
    keys = args.field or sorted(client.fields)
    wb.emit({"record_id": args.record_id, "fields": client.read(args.record_id, keys)})


def write(args, client):
    values = parse_assignments(args.set)
    if not values:
        raise ValueError("Nothing to write; use --set key=value.")
    written, notes = write_values(client, args.record_id, values)
    wb.emit({"record_id": args.record_id, "written": written, "verified": True, "notes": notes})


def options(args, client):
    if args.field not in SELECTS:
        raise ValueError(f"Options exist only for {sorted(SELECTS)}.")
    choices = client.options(args.field)
    if args.field == "platform" and client.platforms:
        choices = [choice for choice in choices if choice in client.platforms]
    wb.emit({"field": args.field, "options": choices,
             "excluded_from_view": client.excluded_priorities if args.field == "priority" else []})


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


def download(args, client):
    # Fetch an attachment already on the record (e.g. a diagnostics zip QA attached) for local reading.
    existing = client.read(args.record_id, [args.field])[args.field] or []
    found = [item for item in existing if item.get("name") == args.name]
    if len(found) != 1:
        raise ValueError(f"Expected exactly one attachment named {args.name!r}, found {len(found)}.")
    output = Path(args.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    target = output / Path(args.name).name
    client.run("+record-download-attachment", "--record-id", args.record_id,
               "--file-token", found[0]["file_token"], "--output", str(target), "--overwrite")
    if not target.is_file() or target.stat().st_size != found[0].get("size"):
        raise LarkError(f"Downloaded {args.name} is missing or its size differs from the record.")
    wb.emit({"record_id": args.record_id, "path": str(target), "size": target.stat().st_size,
             "file_token": found[0]["file_token"]})


def person_ids(value):
    items = value if isinstance(value, list) else [value] if value else []
    return {item.get("id") or item.get("open_id") for item in items if isinstance(item, dict)}


def suggestions(client, query=None):
    # People in the organisation the current user has chatted with, to offer as choices.
    arguments = ["--query", query] if query else []
    return client.contact(*arguments, "--has-chatted", "--page-size", "20")


def assign(args, client):
    if not client.configured("assignee"):
        raise ValueError("bug_report.field_map has no assignee (指派人) field.")
    if not args.name:
        wb.emit({"record_id": args.record_id, "status": "missing",
                 "message": "未指定跟进人，请用户回复跟进人的名字。", "suggestions": suggestions(client)})
        return
    found = client.contact("--query", args.name)
    exact = [user for user in found if user["name"] == args.name]
    chosen = exact if exact else found
    if len(chosen) != 1:
        status = "ambiguous" if chosen else "not_found"
        wb.emit({"record_id": args.record_id, "status": status, "name": args.name,
                 "candidates": chosen, "suggestions": [] if chosen else suggestions(client)})
        return
    user = chosen[0]
    client.upsert({client.field_id("assignee"): [{"id": user["open_id"]}]}, args.record_id)
    if user["open_id"] not in person_ids(client.read(args.record_id, ["assignee"])["assignee"]):
        raise LarkError("指派人 read-back does not contain the assigned user.")
    wb.emit({"record_id": args.record_id, "status": "assigned", "assignee": user, "verified": True})


def suggest_users(args, client):
    wb.emit({"users": suggestions(client, args.query)})


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    for name in ("create", "read", "write", "options", "attach", "download", "assign", "suggest-users"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name not in ("create", "options", "suggest-users"):
            command.add_argument("--record-id", required=True)
        if name == "create":
            command.add_argument("--title", required=True, help="精简的 Bug 描述，也是查重依据。")
            command.add_argument("--record-time", help="ISO 8601 with timezone, or YYYY-MM-DD; default now.")
            command.add_argument("--set", action="append", help="Extra fields, e.g. platform=新框架一期-Web.")
        if name == "read":
            command.add_argument("--field", action="append", help="field_map key; repeatable.")
        if name == "write":
            command.add_argument("--set", action="append", help="key=text or key=@file.")
        if name == "options":
            command.add_argument("--field", required=True, help=f"One of {sorted(SELECTS)}.")
        if name == "attach":
            command.add_argument("--file", action="append", required=True)
            command.add_argument("--field", default="attachments")
        if name == "download":
            command.add_argument("--name", required=True, help="Attachment file name on the record.")
            command.add_argument("--output-dir", required=True)
            command.add_argument("--field", default="attachments")
        if name == "assign":
            command.add_argument("--name", help="跟进人姓名，由用户在对话里提供；缺省时返回建议名单。")
        if name == "suggest-users":
            command.add_argument("--query")
    return result


def main():
    args = parser().parse_args()
    try:
        root = wb.data_root(args)
        client = Feishu(wb.load_config(args, root))
        {"create": create, "read": read, "write": write, "options": options, "attach": attach,
         "download": download, "assign": assign, "suggest-users": suggest_users}[args.operation](args, client)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
