#!/usr/bin/env python3
"""One scheduled round: fix every approved bug of one assignee, one Codex session each.

A round takes a per-assignee lock (a round still running makes the next one skip).
Records this assignee left at 修复中 are from an interrupted round and are marked
修复失败. Then every unresolved record whose 方案状态 is 已批准 (optionally only a
minimum priority and above) is claimed by setting 修复中, gets a run directory with
context.md (root cause, plan, acceptance and the bug context), attachments, diagrams
and fix.json (branch and lane names), and runs `codex exec` there with the
scheduled-mode prompt: fix, PR to main, deploy to PPE (server lane, then web preview,
then Computer canary), verify, write back. The session ends at 已部署待验收 or
修复失败; a session that ends while still 修复中 is marked 修复失败 here.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime
import fcntl
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import common as wb  # noqa: E402
import deploy  # noqa: E402
import feishu  # noqa: E402

SKILL = SCRIPTS.parent / "SKILL.md"
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGES = 6


def schedule_config(cfg):
    defaults = wb.read_json(wb.PLUGIN_ROOT / "config/workbench.example.json").get("execute_schedule", {})
    return {**defaults, **(cfg.get("execute_schedule") or {})}


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


def fix_plan(cfg, record_id):
    return {"branch": f"{deploy.deploy_config(cfg)['branch_prefix']}{record_id.lower()}",
            "lane": deploy.lane_name(cfg, record_id)}


def prompt(record, assignee, run_dir, plan):
    return f"""使用 $tutti-bug-workflow:bug-execute 的「定时模式」修复这一条 Bug（Skill 文件：{SKILL}）。

- record_id：{record['record_id']}
- Bug 描述：{record['title']}
- 优先级：{record.get('priority') or '未填'}
- 跟进人：{assignee['name']}（{assignee['open_id']}）
- 方案状态：已由本轮置为「修复中」
- 修复分支：{plan['branch']}（tutti、tutti-server、tsh-websocket 都用这个名字）
- PPE 泳道：{plan['lane']}（tutti-server 和 tsh-websocket 共用）
- 运行目录（当前目录）：{run_dir}
  - context.md：分析根因、修复方式、验收标准（RD 已批准），以及问题上下文、环境与版本、修复进度等
  - attachments/：现场附件；diagrams/：根因流程图与架构图
  - fix.json：分支名与泳道名

按 Skill 的定时模式完成：修复 → 测试 → 推送并提 PR 到 main → 部署 PPE（server 泳道 → ws 泳道 → 前端预览 → Computer canary，按涉及的端；每次 deploy.py 都带 --record-id，把预览链接、泳道、canary 版本回填到「访问环境」）→ 用本机 Chrome 打开预览按验收标准自验证（涉及 UI 每条用例截图，上传到「修复截图」）→ 回填验证结果。
每一步都用 feishu.py progress 写进「修复进度」。最后把方案状态设为「已部署待验收」，任何一步失败则设为「修复失败」并写明原因。
无人值守：不要提问、不要等待回复。
"""


def run_session(cfg, record, assignee, run_dir, plan, timeout):
    images = sorted(path for path in (run_dir / "attachments").iterdir() if path.suffix.lower() in IMAGES)
    command = [cfg["codex_command"], "exec"]
    for image in images[:MAX_IMAGES]:
        command += ["-i", str(image)]
    command += ["--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check",
                "-C", str(run_dir), "-o", str(run_dir / "last-message.md"), "-"]
    started = time.monotonic()
    with (run_dir / "session.log").open("w", encoding="utf-8") as log:
        try:
            process = subprocess.run(command, input=prompt(record, assignee, run_dir, plan), stdout=log, cwd=run_dir,
                                     stderr=subprocess.STDOUT, text=True, timeout=timeout, check=False)
            exit_code, timed_out = process.returncode, False
        except subprocess.TimeoutExpired:
            exit_code, timed_out = None, True
    return {"exit_code": exit_code, "timed_out": timed_out, "seconds": round(time.monotonic() - started)}


def mark_failed(client, record_id, note):
    """修复中 → 修复失败 with a progress note; quietly skips if the status moved on."""
    fixing, failed = client.plan_status["fixing"], client.plan_status["fix_failed"]
    if feishu.plan_status(client, record_id) != fixing:
        return False
    client.upsert({client.field_id("plan_status"): failed}, record_id)
    feishu.append_progress(client, record_id, f"方案状态 {fixing} → {failed}：{note}")
    return True


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


def fix(args, cfg, client, schedule, assignee, records, runs):
    results = []
    status = client.plan_status
    for record in records:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        run_dir = runs / record["record_id"] / stamp
        outcome = {"record_id": record["record_id"], "title": record["title"],
                   "priority": record.get("priority"), "run_dir": str(run_dir)}
        try:
            plan = fix_plan(cfg, record["record_id"])
            if args.dry_run:
                feishu.prepare_context(client, record["record_id"], run_dir)
                wb.write_json(run_dir / "fix.json", plan)
                results.append({**outcome, **plan, "status": "prepared"})
                continue
            # Claim it: only 已批准 → 修复中 succeeds, so a record RD moved on is skipped.
            if feishu.plan_status(client, record["record_id"]) != status["approved"]:
                results.append({**outcome, "status": "skipped", "reason": "方案状态已不是已批准"})
                continue
            client.upsert({client.field_id("plan_status"): status["fixing"]}, record["record_id"])
            feishu.append_progress(client, record["record_id"],
                                   f"方案状态 {status['approved']} → {status['fixing']}：定时修复开始，"
                                   f"分支 {plan['branch']}，泳道 {plan['lane']}，运行目录 {run_dir}")
            feishu.prepare_context(client, record["record_id"], run_dir)
            wb.write_json(run_dir / "fix.json", plan)
            session = run_session(schedule, record, assignee, run_dir, plan, schedule["timeout_minutes"] * 60)
            final = feishu.plan_status(client, record["record_id"])
            if final == status["fixing"]:
                reason = (f"会话超过 {schedule['timeout_minutes']} 分钟被结束" if session["timed_out"]
                          else f"会话结束（退出码 {session['exit_code']}）但没有更新方案状态")
                mark_failed(client, record["record_id"], f"{reason}，详见 {run_dir}/session.log")
                final = status["fix_failed"]
            results.append({**outcome, **plan, **session, "plan_status": final,
                            "status": "deployed" if final == status["deployed"] else "failed"})
        except (ValueError, OSError, subprocess.TimeoutExpired) as error:
            try:
                mark_failed(client, record["record_id"], f"定时修复出错：{error}")
            except (ValueError, OSError, subprocess.TimeoutExpired):
                pass
            results.append({**outcome, "status": "failed", "error": str(error)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    parser.add_argument("--config")
    parser.add_argument("--assignee", required=True, help="跟进人 open_id（schedule.py 安装时解析）。")
    parser.add_argument("--min-priority", choices=feishu.PRIORITIES)
    parser.add_argument("--record-id", action="append", help="Only these records (still filtered).")
    parser.add_argument("--dry-run", action="store_true", help="Prepare run directories; no claim, no Codex.")
    args = parser.parse_args()
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        root = wb.data_root(args)
        cfg = wb.load_config(args, root)
        schedule = schedule_config(cfg)
        if not shutil.which(schedule["codex_command"]) and not args.dry_run:
            raise ValueError(f"codex not found: {schedule['codex_command']}")
        runs = root / "execute-runs"
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", args.assignee)
        with round_lock(runs / f".scan-{safe}.lock") as acquired:
            if not acquired:
                wb.emit({"ok": True, "started": started, "status": "skipped", "reason": "上一轮还在运行"})
                return 0
            client = feishu.Feishu(cfg)
            users = client.contact("--user-ids", args.assignee)
            assignee = users[0] if len(users) == 1 else {"open_id": args.assignee, "name": args.assignee}
            # Holding the lock means no session of ours is running: 修复中 left over is stale.
            interrupted = []
            if not args.dry_run:
                for record in feishu.candidates(client, args.assignee, status=client.plan_status["fixing"]):
                    if mark_failed(client, record["record_id"], "上一轮修复会话中断（进程退出或机器重启）"):
                        interrupted.append(record["record_id"])
            records = feishu.candidates(client, args.assignee, args.min_priority)
            if args.record_id:
                records = [record for record in records if record["record_id"] in args.record_id]
            results = fix(args, cfg, client, schedule, assignee, records, runs)
            removed = cleanup(runs, schedule["keep_days"])
        summary = {name: sum(1 for item in results if item["status"] == name)
                   for name in ("deployed", "failed", "skipped", "prepared")}
        wb.emit({"ok": True, "started": started, "assignee": assignee, "min_priority": args.min_priority,
                 "interrupted": interrupted, "pending": len(records), "summary": summary, "results": results,
                 "removed_old_runs": removed})
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "started": started, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
