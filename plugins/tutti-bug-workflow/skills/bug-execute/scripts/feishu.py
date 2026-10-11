#!/usr/bin/env python3
"""Feishu Bug record operations for executing an approved fix, via lark-cli.

Stateless: nothing is persisted locally. The agent passes record_id on every call; the
Feishu record in the `bug_report` table is the only source of truth. `check-approval`
confirms 修复方式 ends with a 【RD 批准】 block whose digest still matches the current
分析根因, 修复方式 and 验收标准; any edit after approval fails the check. This skill
writes only 验证结果 and 关联 PR and uploads evidence to 截图、视频、日志; it never
touches the approved fields or 状态 (status changes are manual).
"""

import argparse
import hashlib
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
ATTACHMENT_FIELDS = {"attachments"}
APPROVAL_MARK = "【RD 批准】"
DIGEST = re.compile(r"^摘要：sha256:([0-9a-f]{64})$", re.M)


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


def as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return ",".join(value)
    if isinstance(value, list) and all(isinstance(item, dict) and "text" in item for item in value):
        return "".join(item["text"] for item in value)  # rich-text segments
    return json.dumps(value, ensure_ascii=False)


def text_value(raw):
    if raw.startswith("@"):
        return Path(raw[1:]).expanduser().read_text(encoding="utf-8")
    return raw


def split_approval(solution):
    """Return (solution body, approval block or None)."""
    index = solution.find(APPROVAL_MARK)
    if index < 0:
        return solution.strip(), None
    return solution[:index].strip(), solution[index:].strip()


def digest(root_cause, body, acceptance):
    joined = "\n\x1e\n".join(part.strip() for part in (root_cause, body, acceptance))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


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


def approval_state(client, record_id):
    values = {key: as_text(value) for key, value in client.read(record_id, list(APPROVED)).items()}
    body, block = split_approval(values["solution"])
    problems = []
    if not values["root_cause"].strip():
        problems.append("分析根因为空")
    if not body:
        problems.append("修复方式为空")
    if not values["acceptance"].strip():
        problems.append("验收标准为空")
    fields = {}
    if not block:
        problems.append(f"修复方式里没有 {APPROVAL_MARK}")
    else:
        for line in block.splitlines()[1:]:
            key, _, value = line.partition("：")
            fields[key] = value
        match = DIGEST.search(block)
        if not match:
            problems.append("批准记录缺少摘要")
        elif match.group(1) != digest(values["root_cause"], body, values["acceptance"]):
            problems.append("批准后分析根因、修复方式或验收标准被修改过，需要 RD 重新批准")
    return {"approved": not problems, "problems": problems, "approver": fields.get("批准人"),
            "time": fields.get("时间"), "quote": fields.get("原话"), "source": fields.get("来源"),
            "root_cause": values["root_cause"].strip(), "solution": body,
            "acceptance": values["acceptance"].strip()}


def check_approval(args, client):
    state = approval_state(client, args.record_id)
    wb.emit({"record_id": args.record_id, **state})
    return 0 if state["approved"] else 1


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


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    for name in ("check-approval", "read", "download", "write", "add-pr", "attach"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        command.add_argument("--record-id", required=True)
        if name == "read":
            command.add_argument("--field", action="append", help="field_map key; repeatable.")
        if name in ("download", "attach"):
            command.add_argument("--field", default="attachments", choices=sorted(ATTACHMENT_FIELDS))
        if name == "download":
            command.add_argument("--name", help="One attachment; default all of them.")
            command.add_argument("--output-dir", required=True)
        if name == "attach":
            command.add_argument("--file", action="append", required=True)
        if name == "write":
            command.add_argument("--set", action="append", help=f"key=text or key=@file; keys {list(WRITABLE)}.")
        if name == "add-pr":
            command.add_argument("--url", required=True)
    return result


def main():
    args = parser().parse_args()
    try:
        root = wb.data_root(args)
        client = Feishu(wb.load_config(args, root))
        status = {"check-approval": check_approval, "read": read, "download": download, "write": write,
                  "add-pr": add_pr, "attach": attach}[args.operation](args, client)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    return status or 0


if __name__ == "__main__":
    sys.exit(main())
