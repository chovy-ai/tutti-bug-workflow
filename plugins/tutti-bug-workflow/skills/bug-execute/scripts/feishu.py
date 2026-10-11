#!/usr/bin/env python3
"""Feishu Bug record operations for fixing approved bugs, via lark-cli.

Stateless: nothing is persisted locally. The Feishu record in the `bug_report` table is
the only source of truth, and every step of a fix shows up on it:

- 方案状态 moves 已批准 → 修复中 (claimed by the scheduled round) → 已部署待验收 or
  修复失败. RD sets 已批准 again to retry a failed fix. `set-plan-status` enforces these
  transitions; 待评审/已驳回 stay RD's and bug-solution's business.
- 修复进度 gets one timestamped line per step (branch, PR, lane, preview link, canary
  version, failures) through `progress`, which only appends.
- 验证结果, 关联 PR and the after-fix screenshots in 修复截图 are written at the end.

分析根因, 修复方式, 验收标准 and 状态 are never written.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as wb  # noqa: E402

APPROVED = ("root_cause", "solution", "acceptance")
WRITABLE = ("verification",)
DOWNLOADABLE = {"attachments", "diagrams", "fix_screenshots"}
UPLOADABLE = {"fix_screenshots", "attachments"}
IMAGE_HEADERS = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
SCREENSHOT_NAME = re.compile(r"(fix|before)-rec[A-Za-z0-9]+-\d+[a-z]?-\d{12}\.(png|jpe?g)\Z")
PRIORITIES = ("P00", "P0", "P1", "P2", "P3")  # highest first
# Record fields written into context.md for a fix session, in order.
CONTEXT_FIELDS = (("title", "Bug 描述"), ("priority", "优先级"), ("platform", "所属端"), ("module", "业务模块"),
                  ("plan_status", "方案状态"), ("root_cause", "分析根因"), ("solution", "修复方式"),
                  ("acceptance", "验收标准"), ("context", "问题上下文"), ("env_version", "环境与版本"),
                  ("page_url", "页面链接"), ("pull_requests", "关联 PR"), ("fix_progress", "修复进度"),
                  ("verification", "验证结果"), ("assignee", "指派人"), ("record_time", "记录时间"))


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
        self.identity = table.get("identity") or "user"
        self.timezone = ZoneInfo(table.get("timezone") or "Asia/Shanghai")
        self.fields = {key: value for key, value in (table.get("field_map") or {}).items() if value}
        self.defaults = table.get("defaults") or {}
        self.plan_status = {"approved": "已批准", "fixing": "修复中", "deployed": "已部署待验收",
                            "fix_failed": "修复失败", **(table.get("plan_status") or {})}
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

    def resolve_user(self, name=None):
        """Resolve a person by exact or unique name; no name means the logged-in user."""
        if not name:
            users = self.contact("--user-ids", "me")
            return (users[0] if len(users) == 1 else None), users
        found = self.contact("--query", name)
        exact = [user for user in found if user["name"] == name]
        chosen = exact if exact else found
        return (chosen[0] if len(chosen) == 1 else None), chosen

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

    def upsert(self, values, record_id):
        self.run("+record-upsert", "--json", json.dumps(values, ensure_ascii=False), "--record-id", record_id)


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


def plan_status(client, record_id):
    return as_text(client.read(record_id, ["plan_status"])["plan_status"]).strip()


def transitions(client):
    status = client.plan_status
    return {status["fixing"]: {status["approved"]},
            status["deployed"]: {status["fixing"]},
            status["fix_failed"]: {status["fixing"], status["approved"]}}


def append_progress(client, record_id, message):
    stamp = datetime.now(client.timezone).strftime("%Y-%m-%d %H:%M")
    line = f"[{stamp}] {' '.join(message.split())}"
    existing = as_text(client.read(record_id, ["fix_progress"])["fix_progress"]).rstrip()
    value = f"{existing}\n{line}" if existing else line
    write_and_verify(client, record_id, {"fix_progress": value})
    return line


def approval_state(client, record_id):
    values = {key: as_text(value).strip()
              for key, value in client.read(record_id, [*APPROVED, "plan_status"]).items()}
    allowed = {client.plan_status["approved"], client.plan_status["fixing"]}
    problems = [f"{name}为空" for key, name in (("root_cause", "分析根因"), ("solution", "修复方式"),
                                               ("acceptance", "验收标准")) if not values[key]]
    if values["plan_status"] not in allowed:
        problems.append(f"方案状态是「{values['plan_status'] or '空'}」，需要 RD 在飞书里选「{client.plan_status['approved']}」")
    return {"approved": not problems, "problems": problems, "plan_status": values["plan_status"] or None,
            "root_cause": values["root_cause"], "solution": values["solution"],
            "acceptance": values["acceptance"]}


def check_approval(args, client):
    state = approval_state(client, args.record_id)
    wb.emit({"record_id": args.record_id, **state})
    return 0 if state["approved"] else 1


def set_plan_status(args, client):
    allowed = transitions(client)
    if args.value not in allowed:
        raise ValueError(f"Fixing only sets 方案状态 to {sorted(allowed)}.")
    before = plan_status(client, args.record_id)
    if before not in allowed[args.value]:
        wb.emit({"record_id": args.record_id, "skipped": True, "plan_status": before or None,
                 "reason": f"「{before or '空'}」不能改为「{args.value}」"})
        return 3
    if args.value == client.plan_status["fixing"]:
        problems = approval_state(client, args.record_id)["problems"]
        if problems:
            raise ValueError(f"Not ready to fix: {problems}")
    client.upsert({client.field_id("plan_status"): args.value}, args.record_id)
    if plan_status(client, args.record_id) != args.value:
        raise LarkError("方案状态 read-back differs; another edit may have raced, re-run.")
    line = append_progress(client, args.record_id, f"方案状态 {before} → {args.value}"
                           + (f"：{args.note}" if args.note else ""))
    wb.emit({"record_id": args.record_id, "plan_status": args.value, "previous": before, "progress": line,
             "verified": True})
    return 0


def progress(args, client):
    wb.emit({"record_id": args.record_id, "appended": append_progress(client, args.record_id, args.message)})


def read(args, client):
    keys = args.field or sorted(client.fields)
    wb.emit({"record_id": args.record_id, "fields": client.read(args.record_id, keys)})


def write(args, client):
    values = parse_assignments(args.set)
    if not values:
        raise ValueError("Nothing to write; use --set key=value.")
    write_and_verify(client, args.record_id, values)
    wb.emit({"record_id": args.record_id, "written": sorted(values), "verified": True})


def add_pr(args, client):
    existing = as_text(client.read(args.record_id, ["pull_requests"])["pull_requests"]).strip()
    lines = [line for line in existing.splitlines() if line.strip()]
    if any(args.url in line for line in lines):
        wb.emit({"record_id": args.record_id, "added": False, "pull_requests": lines})
        return
    lines.append(args.url)
    write_and_verify(client, args.record_id, {"pull_requests": "\n".join(lines)})
    wb.emit({"record_id": args.record_id, "added": True, "pull_requests": lines, "verified": True})


def attach(args, client):
    record_id = args.record_id
    files = []
    for raw in args.file:
        file = Path(raw).expanduser().resolve()
        if not file.is_file():
            raise ValueError(f"Not a file: {file}")
        if args.field == "fix_screenshots":
            if not file.read_bytes()[:8].startswith(IMAGE_HEADERS):
                raise ValueError(f"修复截图 only takes PNG or JPEG images: {file.name}")
            if not SCREENSHOT_NAME.fullmatch(file.name):
                raise ValueError(f"Name screenshots fix-<record_id>-<用例编号>-<yyyymmddHHMM>.png "
                                 f"(or before-…): {file.name}")
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


def download_items(client, record_id, items, folder):
    folder.mkdir(parents=True, exist_ok=True)
    saved, names = [], set()
    for item in items:
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
    return saved


def download(args, client):
    items = client.read(args.record_id, [args.field])[args.field] or []
    if args.name:
        items = [item for item in items if item.get("name") == args.name]
        if len(items) != 1:
            raise ValueError(f"Expected exactly one attachment named {args.name!r}, found {len(items)}.")
    wb.emit({"record_id": args.record_id,
             "downloaded": download_items(client, args.record_id, items, Path(args.output_dir).expanduser().resolve())})


def candidates(client, open_id, min_priority=None, status=None):
    """Unresolved records assigned to open_id with the given 方案状态 (default 已批准)."""
    if min_priority and min_priority not in PRIORITIES:
        raise ValueError(f"min_priority must be one of {PRIORITIES}.")
    allowed = PRIORITIES[:PRIORITIES.index(min_priority) + 1] if min_priority else None
    wanted = status or client.plan_status["approved"]
    rows = client.list([[client.field_id("status"), "intersects", [client.defaults.get("status") or "未解决"]],
                        [client.field_id("assignee"), "intersects", [open_id]],
                        [client.field_id("plan_status"), "intersects", [wanted]]],
                       ["title", "record_time", "priority", "plan_status"])
    found = []
    for record_id, values in rows:
        priority = as_text(values["priority"]).strip()
        if as_text(values["plan_status"]).strip() != wanted or (allowed and priority not in allowed):
            continue
        found.append({"record_id": record_id, "title": as_text(values["title"]), "priority": priority,
                      "record_time": as_text(values["record_time"])})
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
    """Write context.md and download attachments and diagrams for one fix session."""
    output.mkdir(parents=True, exist_ok=True)
    keys = [key for key, _ in CONTEXT_FIELDS if key in client.fields]
    values = client.read(record_id, keys + [key for key in ("attachments", "diagrams") if key in client.fields])
    saved = download_items(client, record_id, values.get("attachments") or [], output / "attachments")
    diagrams = download_items(client, record_id, values.get("diagrams") or [], output / "diagrams")
    lines = [f"# Bug 记录 {record_id}", ""]
    for key, label in CONTEXT_FIELDS:
        if key in keys:
            lines += [f"## {label}", "", as_text(values.get(key)).strip() or "（空）", ""]
    lines += ["## 附件", ""]
    lines += [f"- attachments/{Path(item['path']).name}（{item['size']} 字节）" for item in saved] or ["（无）"]
    lines += ["", "## 根因图", ""]
    lines += [f"- diagrams/{Path(item['path']).name}" for item in diagrams] or ["（无）"]
    (output / "context.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"record_id": record_id, "context": str(output / "context.md"), "attachments": saved,
            "diagrams": diagrams, "title": as_text(values.get("title"))}


def context(args, client):
    wb.emit(prepare_context(client, args.record_id, Path(args.output_dir).expanduser().resolve()))


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    names = ("check-approval", "set-plan-status", "progress", "read", "download", "write", "add-pr", "attach",
             "scan", "context")
    for name in names:
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name != "scan":
            command.add_argument("--record-id", required=True)
        if name == "set-plan-status":
            command.add_argument("--value", required=True, help="修复中／已部署待验收／修复失败。")
            command.add_argument("--note", help="一并写进修复进度的说明，如失败原因。")
        if name == "progress":
            command.add_argument("--message", required=True)
        if name == "read":
            command.add_argument("--field", action="append", help="field_map key; repeatable.")
        if name == "download":
            command.add_argument("--field", default="attachments", choices=sorted(DOWNLOADABLE))
            command.add_argument("--name", help="One attachment; default all of them.")
            command.add_argument("--output-dir", required=True)
        if name == "attach":
            command.add_argument("--field", default="fix_screenshots", choices=sorted(UPLOADABLE))
            command.add_argument("--file", action="append", required=True)
        if name == "write":
            command.add_argument("--set", action="append", help=f"key=text or key=@file; keys {list(WRITABLE)}.")
        if name == "add-pr":
            command.add_argument("--url", required=True)
        if name == "scan":
            command.add_argument("--assignee", help="跟进人姓名；缺省为当前登录用户。")
            command.add_argument("--min-priority", choices=PRIORITIES)
        if name == "context":
            command.add_argument("--output-dir", required=True)
    return result


def main():
    args = parser().parse_args()
    try:
        root = wb.data_root(args)
        client = Feishu(wb.load_config(args, root))
        status = {"check-approval": check_approval, "set-plan-status": set_plan_status, "progress": progress,
                  "read": read, "download": download, "write": write, "add-pr": add_pr, "attach": attach,
                  "scan": scan, "context": context}[args.operation](args, client)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    return status or 0


if __name__ == "__main__":
    sys.exit(main())
