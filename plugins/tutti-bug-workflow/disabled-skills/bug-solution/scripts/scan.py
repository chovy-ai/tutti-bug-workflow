#!/usr/bin/env python3
"""One scheduled round: analyse every pending bug of one assignee, one Codex session each.

A round takes a per-assignee lock (a round still running makes the next one skip),
lists the assignee's unresolved records whose 方案状态 is empty, 未处理 or 已驳回
(optionally only a minimum priority and above), syncs the global code checkouts to the
latest main, and for each record prepares a run directory with context.md, the
downloaded attachments and code.json, then runs `codex exec` there with the
scheduled-mode prompt. Every pending record is processed; a session that times out or
does not leave 方案状态 at 待评审 counts as failed and is retried next round. Run
directories older than keep_days are removed.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import common as wb  # noqa: E402
import feishu  # noqa: E402

SKILL = SCRIPTS.parent / "SKILL.md"
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGES = 6


def schedule_config(cfg):
    defaults = wb.read_json(wb.PLUGIN_ROOT / "config/workbench.example.json").get("solution_schedule", {})
    return {**defaults, **(cfg.get("solution_schedule") or {})}


@contextmanager
def round_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def sync_code(args):
    command = [sys.executable, str(SCRIPTS / "repos.py"), "sync"]
    for flag in ("data_dir", "config"):
        if getattr(args, flag):
            command += [f"--{flag.replace('_', '-')}", getattr(args, flag)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800, check=False)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {"ok": False, "error": (result.stderr or result.stdout).strip()[-500:]}
    if result.returncode or not report.get("ok"):
        raise ValueError(f"Code sync failed: {report.get('error')}")
    return report["repositories"]


def prompt(record, assignee, run_dir):
    return f"""使用 $tutti-bug-workflow:bug-solution 的「定时模式」分析这一条 Bug（Skill 文件：{SKILL}）。

- record_id：{record['record_id']}
- Bug 描述：{record['title']}
- 优先级：{record.get('priority') or '未填'}
- 方案状态：{record.get('plan_status') or '（空）'}{'（RD 已驳回上一版，先读 context.md 里的「驳回意见」和上一版内容）' if record.get('plan_status') == '已驳回' else ''}
- 跟进人：{assignee['name']}（{assignee['open_id']}）
- 运行目录（当前目录）：{run_dir}
  - context.md：这条 Bug 记录的全部字段（问题上下文、环境与版本、页面链接、关联 ID 等）
  - attachments/：记录上的全部附件（截图、视频、Web／Server／Computer 日志）
  - code.json：本轮已同步到最新 main 的全局代码检出路径与 SHA

先完整阅读 context.md 和 attachments/ 里的日志与截图，从现场出发定位根因，再按 Skill 的定时模式完成：
分析根因（开头先写两三句大白话的根因、复现路径、预期工作流程，再写细节）、流程图与架构图 PNG（上传到「根因图」）、修复方式与验收标准，全部写回这条记录，最后把方案状态设为「待评审」。
无人值守：不要提问、不要等待回复；现场不足的地方写进根因的「待确认」后照常完成。
写入一律带 --if-open；返回 skipped（方案状态已被 RD 改动）就停止，不覆盖。
"""


def run_session(cfg, record, assignee, run_dir, timeout):
    images = sorted(path for path in (run_dir / "attachments").iterdir() if path.suffix.lower() in IMAGES)
    command = [cfg["codex_command"], "exec"]
    for image in images[:MAX_IMAGES]:
        command += ["-i", str(image)]
    command += ["--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check",
                "-C", str(run_dir), "-o", str(run_dir / "last-message.md"), "-"]
    started = time.monotonic()
    with (run_dir / "session.log").open("w", encoding="utf-8") as log:
        try:
            process = subprocess.run(command, input=prompt(record, assignee, run_dir), stdout=log, cwd=run_dir,
                                     stderr=subprocess.STDOUT, text=True, timeout=timeout, check=False)
            exit_code, timed_out = process.returncode, False
        except subprocess.TimeoutExpired:
            exit_code, timed_out = None, True
    return {"exit_code": exit_code, "timed_out": timed_out, "seconds": round(time.monotonic() - started)}


def cleanup(runs, keep_days):
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for record_dir in runs.glob("rec*"):
        for run in record_dir.iterdir():
            if run.is_dir() and run.stat().st_mtime < cutoff:
                shutil.rmtree(run, ignore_errors=True)
                removed += 1
        if record_dir.is_dir() and not any(record_dir.iterdir()):
            record_dir.rmdir()
    return removed


def analyse(args, cfg, client, schedule, assignee, records, code, runs):
    results = []
    for record in records:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = runs / record["record_id"] / stamp
        outcome = {"record_id": record["record_id"], "title": record["title"],
                   "priority": record.get("priority"), "run_dir": str(run_dir)}
        try:
            # Re-check right before starting: RD may have moved the plan on meanwhile.
            if feishu.guard(client, record["record_id"]) is None:
                results.append({**outcome, "status": "skipped", "reason": "方案状态已不在待分析范围"})
                continue
            feishu.prepare_context(client, record["record_id"], run_dir)
            wb.write_json(run_dir / "code.json", {"repositories": code})
            if args.dry_run:
                results.append({**outcome, "status": "prepared"})
                continue
            session = run_session(schedule, record, assignee, run_dir, schedule["timeout_minutes"] * 60)
            done = feishu.plan_status(client, record["record_id"]) == client.plan_status["review"]
            status = "analysed" if done and not session["timed_out"] else "failed"
            results.append({**outcome, **session, "status": status})
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            results.append({**outcome, "status": "failed", "error": str(error)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    parser.add_argument("--config")
    parser.add_argument("--assignee", required=True, help="跟进人 open_id（schedule.py 安装时解析）。")
    parser.add_argument("--min-priority", choices=feishu.PRIORITIES)
    parser.add_argument("--record-id", action="append", help="Only these records (still filtered).")
    parser.add_argument("--dry-run", action="store_true", help="Prepare run directories, skip Codex.")
    args = parser.parse_args()
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        root = wb.data_root(args)
        cfg = wb.load_config(args, root)
        schedule = schedule_config(cfg)
        if not shutil.which(schedule["codex_command"]) and not args.dry_run:
            raise ValueError(f"codex not found: {schedule['codex_command']}")
        runs = root / "solution-runs"
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", args.assignee)
        with round_lock(runs / f".scan-{safe}.lock") as acquired:
            if not acquired:
                wb.emit({"ok": True, "started": started, "status": "skipped",
                         "reason": "上一轮还在运行"})
                return 0
            client = feishu.Feishu(cfg)
            users = client.contact("--user-ids", args.assignee)
            assignee = users[0] if len(users) == 1 else {"open_id": args.assignee, "name": args.assignee}
            records = feishu.candidates(client, args.assignee, args.min_priority)
            if args.record_id:
                records = [record for record in records if record["record_id"] in args.record_id]
            code = sync_code(args) if records else []
            results = analyse(args, cfg, client, schedule, assignee, records, code, runs)
            removed = cleanup(runs, schedule["keep_days"])
        summary = {status: sum(1 for item in results if item["status"] == status)
                   for status in ("analysed", "failed", "skipped", "prepared")}
        wb.emit({"ok": True, "started": started, "assignee": assignee, "min_priority": args.min_priority,
                 "pending": len(records), "summary": summary, "results": results,
                 "removed_old_runs": removed})
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "started": started, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
