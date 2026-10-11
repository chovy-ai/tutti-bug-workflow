#!/usr/bin/env python3
"""Feishu Bug record operations for root-cause analysis and solution design, via lark-cli.

Stateless: nothing is persisted locally. The agent passes record_id on every call; the
Feishu record in the `bug_report` table is the only source of truth. This skill writes
分析根因, 修复方式 and 验收标准, and records the RD approval as a 【RD 批准】 block at the
end of 修复方式. The block carries a digest of the approved root cause, solution and
acceptance text, so any later change to them clears the approval. 状态 is never written:
status changes are manual.
"""

import argparse
from datetime import datetime
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

# Fields this skill writes. The approval block inside `solution` is managed by `approve`.
WRITABLE = ("root_cause", "solution", "acceptance")
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


def current(client, record_id):
    values = {key: as_text(value) for key, value in client.read(record_id, list(WRITABLE)).items()}
    body, block = split_approval(values["solution"])
    return values["root_cause"].strip(), body, values["acceptance"].strip(), block


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
        value = text_value(raw).strip()
        if APPROVAL_MARK in value:
            raise ValueError(f"{APPROVAL_MARK} is written only by `approve`; remove it from {key}.")
        result[key] = value
    return result


def read(args, client):
    keys = args.field or sorted(client.fields)
    wb.emit({"record_id": args.record_id, "fields": client.read(args.record_id, keys)})


def write(args, client):
    values = parse_assignments(args.set)
    if not values:
        raise ValueError("Nothing to write; use --set key=value.")
    root_cause, body, acceptance, block = current(client, args.record_id)
    new = {"root_cause": values.get("root_cause", root_cause), "solution": values.get("solution", body),
           "acceptance": values.get("acceptance", acceptance)}
    cleared = False
    if block:
        match = DIGEST.search(block)
        if match and match.group(1) == digest(new["root_cause"], new["solution"], new["acceptance"]):
            if "solution" in values:
                values["solution"] = f"{values['solution']}\n\n{block}"
        else:
            # The approved content changed: drop the approval so execution cannot use it.
            values["solution"] = new["solution"]
            cleared = True
    write_and_verify(client, args.record_id, values)
    wb.emit({"record_id": args.record_id, "written": sorted(values), "verified": True,
             "approval_cleared": cleared})


def approve(args, client):
    root_cause, body, acceptance, _ = current(client, args.record_id)
    missing = [name for name, value in (("分析根因", root_cause), ("修复方式", body), ("验收标准", acceptance))
               if not value]
    if missing:
        raise ValueError(f"Write {missing} before recording an approval.")
    found = client.contact("--query", args.approver)
    exact = [user for user in found if user["name"] == args.approver]
    chosen = exact if exact else found
    if len(chosen) != 1:
        wb.emit({"record_id": args.record_id, "status": "ambiguous" if chosen else "not_found",
                 "approver": args.approver, "candidates": chosen})
        return 1
    user = chosen[0]
    lines = [APPROVAL_MARK,
             f"批准人：{user['name']}（{user['open_id']}）",
             f"时间：{datetime.now(client.timezone).strftime('%Y-%m-%d %H:%M:%S')}",
             f"原话：{' '.join(args.quote.split())}"]
    if args.source:
        lines.append(f"来源：{' '.join(args.source.split())}")
    lines.append(f"摘要：sha256:{digest(root_cause, body, acceptance)}")
    block = "\n".join(lines)
    write_and_verify(client, args.record_id, {"solution": f"{body}\n\n{block}"})
    wb.emit({"record_id": args.record_id, "status": "approved", "approver": user, "verified": True,
             "approval": block})
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


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    for name in ("read", "download", "write", "approve"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        command.add_argument("--record-id", required=True)
        if name == "read":
            command.add_argument("--field", action="append", help="field_map key; repeatable.")
        if name == "download":
            command.add_argument("--name", help="One attachment; default all of them.")
            command.add_argument("--output-dir", required=True)
            command.add_argument("--field", default="attachments", choices=sorted(ATTACHMENT_FIELDS))
        if name == "write":
            command.add_argument("--set", action="append", help=f"key=text or key=@file; keys {list(WRITABLE)}.")
        if name == "approve":
            command.add_argument("--approver", required=True, help="批准的 RD 姓名，按通讯录唯一匹配。")
            command.add_argument("--quote", required=True, help="RD 批准的原话。")
            command.add_argument("--source", help="批准出处，如飞书消息链接或「当前对话」。")
    return result


def main():
    args = parser().parse_args()
    try:
        root = wb.data_root(args)
        client = Feishu(wb.load_config(args, root))
        status = {"read": read, "download": download, "write": write,
                  "approve": approve}[args.operation](args, client)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    return status or 0


if __name__ == "__main__":
    sys.exit(main())
