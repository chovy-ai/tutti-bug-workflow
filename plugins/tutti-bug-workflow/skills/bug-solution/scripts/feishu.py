#!/usr/bin/env python3
"""Feishu Bug record operations for root-cause analysis and solution design, via lark-cli.

Stateless: nothing is persisted locally. The agent passes record_id on every call; the
Feishu record in the `bug_report` table is the only source of truth. The scheduled analysis
picks records whose 方案状态 is empty, 未处理 or 已驳回, writes 分析根因, 修复方式 and
验收标准, uploads diagrams to 根因图, then sets 方案状态 to 待评审. RD approves or rejects
by changing 方案状态 in Feishu (with 驳回意见 for a rejection). Every write is guarded:
if 方案状态 left the open set meanwhile, nothing is written. 状态 is never written.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as wb  # noqa: E402

# Fields this skill writes; 方案状态 only through `set-plan-status`, and only to 待评审.
WRITABLE = ("root_cause", "solution", "acceptance")
DOWNLOADABLE = {"attachments", "diagrams"}
UPLOADABLE = {"diagrams"}
# Record fields written into context.md for a scheduled analysis session, in order.
CONTEXT_FIELDS = (("title", "Bug 描述"), ("context", "问题上下文"), ("env_version", "环境与版本"),
                  ("page_url", "页面链接"), ("platform", "所属端"), ("priority", "优先级"),
                  ("module", "业务模块"), ("issue_type", "问题类型"), ("status", "状态"),
                  ("reporter", "提交人"), ("assignee", "指派人"), ("record_time", "记录时间"),
                  ("plan_status", "方案状态"), ("rejection", "驳回意见"),
                  ("root_cause", "分析根因（上一版）"), ("solution", "修复方式（上一版）"),
                  ("acceptance", "验收标准（上一版）"))


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
        self.defaults = table.get("defaults") or {}
        self.plan_status = {"open": ["未处理", "已驳回"], "review": "待评审", "approved": "已批准",
                            "rejected": "已驳回", **(table.get("plan_status") or {})}
        self.base = table.get("base_token")
        self.table = table.get("table_id")
        self.identity = table.get("identity") or "user"
        self.timezone = ZoneInfo(table.get("timezone") or "Asia/Shanghai")
        self.fields = {key: value for key, value in (table.get("field_map") or {}).items() if value}
        if not self.base or not self.table or "title" not in self.fields:
            raise ValueError("Config needs bug_report.base_token, table_id and field_map.title.")
        command = os.environ.get("LARK_CLI")
        if not command:
            command = next((item["command"] for item in cfg.get("cli_dependencies", [])
                            if item.get("name") == "lark-cli"), "lark-cli")
        self.command = command

    def field_id(self, key):
        value = self.fields.get(key)
        if not value:
            raise ValueError(f"bug_report.field_map has no entry for {key!r}.")
        return value

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
                 "department": user.get("department") or None}
                for user in data.get("users") or [] if user.get("open_id")]

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

    def upsert(self, values, record_id):
        self.run("+record-upsert", "--json", json.dumps(values, ensure_ascii=False), "--record-id", record_id)

    def list(self, conditions, keys):
        """All records matching conditions, as (record_id, {key: value}) pairs."""
        arguments = ["--format", "json", "--limit", "200",
                     "--filter-json", json.dumps({"logic": "and", "conditions": conditions}, ensure_ascii=False)]
        for key in keys:
            arguments += ["--field-id", self.field_id(key)]
        rows, offset = [], 0
        while True:
            data = self.run("+record-list", *arguments, "--offset", str(offset))
            ids = data.get("record_id_list") or []
            for record_id, values in zip(ids, data.get("data") or []):
                row = dict(zip(data.get("field_id_list") or [], values))
                rows.append((record_id, {key: row.get(self.field_id(key)) for key in keys}))
            offset += len(ids)
            if not data.get("has_more") or not ids:
                return rows

    def resolve_user(self, name=None):
        """Resolve a person by exact or unique name; no name means the logged-in user."""
        if not name:
            users = self.contact("--user-ids", "me")
            return (users[0] if len(users) == 1 else None), users
        found = self.contact("--query", name)
        exact = [user for user in found if user["name"] == name]
        chosen = exact if exact else found
        return (chosen[0] if len(chosen) == 1 else None), chosen


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    if isinstance(value, list) and all(isinstance(item, dict) and "text" in item for item in value):
        return "".join(item["text"] for item in value)  # rich-text segments
    if isinstance(value, list) and all(isinstance(item, dict) and "name" in item for item in value):
        return "、".join(item["name"] for item in value)  # people or attachments
    if isinstance(value, dict) and "link" in value:
        return value.get("link") or ""
    return json.dumps(value, ensure_ascii=False)


def text_value(raw):
    if raw.startswith("@"):
        return Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    return raw


def write_and_verify(client, record_id, values):
    client.upsert({client.field_id(key): value for key, value in values.items()}, record_id)
    actual = client.read(record_id, sorted(values))
    mismatched = [key for key, value in values.items() if as_text(actual.get(key)).strip() != value.strip()]
    if mismatched:
        raise LarkError(f"Read-back differs for {mismatched}; another edit may have raced, re-run.")


def parse_assignments(items):
    result = {}
    for item in items or []:
        key, separator, raw = item.partition("=")
        if not separator:
            raise ValueError(f"--set expects key=value or key=@file, got {item!r}.")
        if key not in WRITABLE:
            raise ValueError(f"{key!r} cannot be written by this skill; allowed: {list(WRITABLE)}.")
        if key in result:
            raise ValueError(f"{key!r} given twice.")
        result[key] = text_value(raw).strip()
    return result


def read(args, client):
    keys = args.field or sorted(client.fields)
    wb.emit({"record_id": args.record_id, "fields": client.read(args.record_id, keys)})


def plan_status(client, record_id):
    return as_text(client.read(record_id, ["plan_status"])["plan_status"]).strip()


def is_open(client, status):
    return not status or status in client.plan_status["open"]


def guard(client, record_id):
    """Return the current 方案状态 if analysis may still write, else None."""
    status = plan_status(client, record_id)
    return status if is_open(client, status) else None


def write(args, client):
    values = parse_assignments(args.set)
    if not values:
        raise ValueError("Nothing to write; use --set key=value.")
    if args.if_open and guard(client, args.record_id) is None:
        # RD moved the plan on (待评审/已批准) since the scan: never overwrite.
        wb.emit({"record_id": args.record_id, "skipped": True, "plan_status": plan_status(client, args.record_id)})
        return 3
    write_and_verify(client, args.record_id, values)
    wb.emit({"record_id": args.record_id, "written": sorted(values), "verified": True})
    return 0


def set_plan_status(args, client):
    review = client.plan_status["review"]
    if args.value != review:
        raise ValueError(f"The analysis only sets 方案状态 to {review}; 已批准/已驳回 are RD's choice.")
    before = guard(client, args.record_id)
    if before is None:
        wb.emit({"record_id": args.record_id, "skipped": True, "plan_status": plan_status(client, args.record_id)})
        return 3
    missing = [name for key, name in (("root_cause", "分析根因"), ("solution", "修复方式"), ("acceptance", "验收标准"))
               if not as_text(client.read(args.record_id, [key])[key]).strip()]
    if missing:
        raise ValueError(f"Write {missing} before handing the plan to review.")
    client.upsert({client.field_id("plan_status"): review}, args.record_id)
    if plan_status(client, args.record_id) != review:
        raise LarkError("方案状态 read-back differs; another edit may have raced, re-run.")
    wb.emit({"record_id": args.record_id, "plan_status": review, "previous": before or "（空）", "verified": True})
    return 0


def download(args, client):
    existing = client.read(args.record_id, [args.field])[args.field] or []
    if args.name:
        found = [item for item in existing if item.get("name") == args.name]
        if len(found) != 1:
            raise ValueError(f"Expected exactly one attachment named {args.name!r}, found {len(found)}.")
    else:
        found = existing
    if len({item.get("name") for item in found}) != len(found):
        raise ValueError("Several attachments share a name; download them one by one with --name.")
    output = Path(args.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    saved = []
    for item in found:
        target = output / Path(item["name"]).name
        client.run("+record-download-attachment", "--record-id", args.record_id,
                   "--file-token", item["file_token"], "--output", str(target), "--overwrite")
        if not target.is_file() or target.stat().st_size != item.get("size"):
            raise LarkError(f"Downloaded {item['name']} is missing or its size differs from the record.")
        saved.append({"name": item["name"], "path": str(target), "size": item.get("size")})
    wb.emit({"record_id": args.record_id, "downloaded": saved})


def attach(args, client):
    record_id = args.record_id
    files = []
    for raw in args.file:
        file = Path(raw).expanduser().resolve()
        if not file.is_file():
            raise ValueError(f"Not a file: {file}")
        if args.field == "diagrams" and file.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"根因图 only takes PNG files: {file.name}")
        files.append((file, file.stat().st_size))
    if len({file.name for file, _ in files}) != len(files):
        raise ValueError("Files uploaded together need distinct names for read-back matching.")
    existing = client.read(record_id, [args.field])[args.field] or []
    # The record is the source of truth: a file with the same name and size is already attached.
    attached = {(item.get("name"), item.get("size")) for item in existing}
    pending = [(file, size) for file, size in files if (file.name, size) not in attached]
    uploaded = []
    if pending:
        arguments = ["--record-id", record_id, "--field-id", client.field_id(args.field)]
        for file, _ in pending:
            arguments += ["--file", str(file)]
        client.run("+record-upload-attachment", *arguments)
        present = {item.get("file_token") for item in existing}
        added = [item for item in client.read(record_id, [args.field])[args.field] or []
                 if item.get("file_token") not in present]
        for file, size in pending:
            match = [item for item in added if item.get("name") == file.name and item.get("size") == size]
            if len(match) != 1:
                raise LarkError(f"Uploaded {file.name} was not found exactly once on read-back.")
            uploaded.append({"name": file.name, "size": size, "file_token": match[0]["file_token"]})
    wb.emit({"record_id": record_id, "uploaded": uploaded, "verified": True,
             "already_attached": [file.name for file, size in files if (file.name, size) in attached]})


PRIORITIES = ("P00", "P0", "P1", "P2", "P3")  # highest first


def candidates(client, open_id, min_priority=None):
    """Unresolved records assigned to open_id whose 方案状态 is empty, 未处理 or 已驳回.

    With min_priority, only that priority and higher; records without a priority are left
    out. Ordered by priority, then oldest first.
    """
    if min_priority and min_priority not in PRIORITIES:
        raise ValueError(f"min_priority must be one of {PRIORITIES}.")
    allowed = PRIORITIES[:PRIORITIES.index(min_priority) + 1] if min_priority else None
    status = client.defaults.get("status") or "未解决"
    rows = client.list([[client.field_id("status"), "intersects", [status]],
                        [client.field_id("assignee"), "intersects", [open_id]]],
                       ["title", "plan_status", "record_time", "priority"])
    found = []
    for record_id, values in rows:
        priority = as_text(values["priority"]).strip()
        status = as_text(values["plan_status"]).strip()
        if not is_open(client, status) or (allowed and priority not in allowed):
            continue
        found.append({"record_id": record_id, "title": as_text(values["title"]), "priority": priority,
                      "plan_status": status or "（空）", "record_time": as_text(values["record_time"])})
    rank = {name: index for index, name in enumerate(PRIORITIES)}
    return sorted(found, key=lambda item: (rank.get(item["priority"], len(rank)), item["record_time"]))


def scan(args, client):
    user, chosen = client.resolve_user(args.assignee)
    if not user:
        wb.emit({"status": "ambiguous" if chosen else "not_found", "assignee": args.assignee,
                 "candidates": chosen})
        return 1
    wb.emit({"assignee": user, "min_priority": args.min_priority,
             "records": candidates(client, user["open_id"], args.min_priority)})
    return 0


def prepare_context(client, record_id, output):
    """Write context.md and download every attachment for one analysis session."""
    output.mkdir(parents=True, exist_ok=True)
    keys = [key for key, _ in CONTEXT_FIELDS if key in client.fields]
    values = client.read(record_id, keys + ["attachments"])
    folder = output / "attachments"
    folder.mkdir(exist_ok=True)
    saved = []
    names = set()
    for item in values.get("attachments") or []:
        name = Path(item["name"]).name
        if name in names:
            name = f"{item['file_token'][:8]}-{name}"
        names.add(name)
        target = folder / name
        client.run("+record-download-attachment", "--record-id", record_id,
                   "--file-token", item["file_token"], "--output", str(target), "--overwrite")
        if not target.is_file() or target.stat().st_size != item.get("size"):
            raise LarkError(f"Downloaded {item['name']} is missing or its size differs from the record.")
        saved.append({"name": item["name"], "path": str(target), "size": item.get("size")})
    lines = [f"# Bug 记录 {record_id}", ""]
    for key, label in CONTEXT_FIELDS:
        if key not in keys:
            continue
        text = as_text(values.get(key)).strip()
        lines += [f"## {label}", "", text or "（空）", ""]
    lines += ["## 附件", ""]
    lines += [f"- attachments/{Path(item['path']).name}（{item['size']} 字节）" for item in saved] or ["（无）"]
    (output / "context.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"record_id": record_id, "context": str(output / "context.md"), "attachments": saved,
            "title": as_text(values.get("title"))}


def context(args, client):
    wb.emit(prepare_context(client, args.record_id, Path(args.output_dir).expanduser().resolve()))


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    for name in ("read", "download", "write", "set-plan-status", "attach", "scan", "context"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name != "scan":
            command.add_argument("--record-id", required=True)
        if name == "read":
            command.add_argument("--field", action="append", help="field_map key; repeatable.")
        if name == "download":
            command.add_argument("--name", help="One attachment; default all of them.")
            command.add_argument("--output-dir", required=True)
            command.add_argument("--field", default="attachments", choices=sorted(DOWNLOADABLE))
        if name == "write":
            command.add_argument("--set", action="append", help=f"key=text or key=@file; keys {list(WRITABLE)}.")
            command.add_argument("--if-open", action="store_true",
                                 help="Skip the write (exit 3) unless 方案状态 is empty, 未处理 or 已驳回.")
        if name == "set-plan-status":
            command.add_argument("--value", required=True, help="只能是「待评审」。")
        if name == "attach":
            command.add_argument("--file", action="append", required=True)
            command.add_argument("--field", default="diagrams", choices=sorted(UPLOADABLE))
        if name == "scan":
            command.add_argument("--assignee", help="跟进人姓名；缺省为当前登录用户。")
            command.add_argument("--min-priority", choices=PRIORITIES, help="只看该优先级及以上。")
        if name == "context":
            command.add_argument("--output-dir", required=True)
    return result


def main():
    args = parser().parse_args()
    try:
        root = wb.data_root(args)
        client = Feishu(wb.load_config(args, root))
        status = {"read": read, "download": download, "write": write, "set-plan-status": set_plan_status,
                  "attach": attach, "scan": scan, "context": context}[args.operation](args, client)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    return status or 0


if __name__ == "__main__":
    sys.exit(main())
