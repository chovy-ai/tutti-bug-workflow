#!/usr/bin/env python3
"""Deploy a fix branch to PPE through the repositories' GitHub workflows, and wait for it.

- `fix-names --issue KEY`: the per-bug names derived from the Multica issue key (`TES-123`):
  fix branch `codex/bug-<key in lower case>` and lane `ppe-bug-<same>`, shared by
  tutti-server and tsh-websocket (both deploy into namespace `lane-<lane>`).
- `server --branch B --lane L`: tutti-server `deploy-lane.yml` on the branch, with the
  configured inputs (connector authorization off for fresh lanes).
- `websocket --branch B --lane L`: tsh-websocket `deploy-lane.yml` on the branch. A fresh
  lane needs its WebSocket V2 infrastructure first, which is a reviewed manual step: when
  it is missing the run fails and the failure log says so.
- `web --branch B [--server-lane L]`: tutti `platform-web-preview.yml`, dispatched from
  main for the branch, pointing at the server lane; returns the preview link.
- `computer --branch B`: tutti `computer-artifacts-release.yml` (Computer Canary) on the
  branch; returns the canary version.
- `destroy-lane --lane L [--service server|websocket]`: the lane's `destroy-lane.yml`, run
  only when asked.

Each command dispatches with `gh workflow run`, finds the run, waits with `gh run watch`
and reports the run URL and conclusion, plus the tail of the failed steps' log when it
fails, and the link to try the fix (`access_url`: the web preview, or the canary run page
for a Computer-only fix). Order is the caller's job: server, websocket, web, then computer.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as wb  # noqa: E402

LANE = re.compile(r"[a-z]([a-z0-9-]{0,38}[a-z0-9])?\Z")  # tutti-server
WS_LANE = re.compile(r"ppe-[a-z0-9]+(-[a-z0-9]+)*\Z")  # tsh-websocket
ISSUE_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]*-[0-9]+\Z")
RUN_URL = re.compile(r"https://github\.com/[^\s]+/actions/runs/(\d+)")


def deploy_config(cfg):
    defaults = wb.read_json(wb.PLUGIN_ROOT / "config/workbench.example.json").get("deploy", {})
    section = cfg.get("deploy") or {}
    return {key: {**defaults.get(key, {}), **section.get(key, {})} if isinstance(defaults.get(key), dict)
            else section.get(key, defaults.get(key)) for key in {*defaults, *section}}


def gh(*arguments, timeout=120):
    command = [os.environ.get("GH") or "gh", *arguments]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError(f"gh {' '.join(arguments[:2])} failed: {(result.stderr or result.stdout).strip()[-800:]}")
    return result.stdout


def fix_names(cfg, issue):
    if not ISSUE_KEY.fullmatch(issue or ""):
        raise ValueError(f"Issue must be a Multica issue key like TES-123: {issue!r}.")
    short = issue.lower()
    config = deploy_config(cfg)
    lane = f"{config['server']['lane_prefix']}{short}"
    if not LANE.fullmatch(lane) or not WS_LANE.fullmatch(lane):
        raise ValueError(f"Lane {lane!r} must suit both tutti-server and tsh-websocket lane names.")
    return {"short_id": short, "branch": f"{config['branch_prefix']}{short}", "lane": lane}


def find_run(repository, workflow, ref, since, output):
    match = RUN_URL.search(output)
    if match:
        return int(match.group(1))
    # Older gh does not print the run URL: take the newest dispatch on this ref since we started.
    for _ in range(20):
        runs = json.loads(gh("run", "list", "-R", repository, "--workflow", workflow, "--branch", ref,
                             "--event", "workflow_dispatch", "--limit", "10",
                             "--json", "databaseId,createdAt"))
        fresh = [run for run in runs
                 if datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00")) >= since]
        if fresh:
            return max(fresh, key=lambda run: run["createdAt"])["databaseId"]
        time.sleep(3)
    raise ValueError(f"Dispatched {workflow} on {ref} but could not find its run.")


def dispatch_and_wait(repository, workflow, ref, fields, wait, timeout_minutes):
    since = datetime.now(timezone.utc) - timedelta(seconds=10)
    arguments = ["workflow", "run", workflow, "-R", repository, "--ref", ref]
    for key, value in fields.items():
        arguments += ["-f", f"{key}={value}"]
    run_id = find_run(repository, workflow, ref, since, gh(*arguments))
    if wait:
        try:
            # Exit status is checked through `run view` below, so a failed run is reported, not raised.
            subprocess.run([os.environ.get("GH") or "gh", "run", "watch", str(run_id), "-R", repository,
                            "--interval", "30", "--exit-status"], capture_output=True, text=True,
                           timeout=timeout_minutes * 60, check=False)
        except subprocess.TimeoutExpired:
            pass
    view = json.loads(gh("run", "view", str(run_id), "-R", repository,
                         "--json", "status,conclusion,url,headSha,attempt,displayTitle"))
    result = {"repository": repository, "workflow": workflow, "ref": ref, "inputs": fields, "run_id": run_id,
              "url": view.get("url"), "status": view.get("status"), "conclusion": view.get("conclusion"),
              "head_sha": view.get("headSha"), "attempt": view.get("attempt") or 1,
              "ok": view.get("status") == "completed" and view.get("conclusion") == "success"}
    if view.get("status") == "completed" and not result["ok"]:
        try:
            result["failed_log_tail"] = gh("run", "view", str(run_id), "-R", repository, "--log-failed",
                                           timeout=300).splitlines()[-60:]
        except (ValueError, subprocess.TimeoutExpired):
            result["failed_log_tail"] = None
    return result


def access_url(service, result):
    """The clickable link to try a deployed side, if it has one."""
    return {"web": result.get("preview_url"), "computer": result.get("url")}.get(service)


def server(args, cfg):
    section = deploy_config(cfg)["server"]
    if not LANE.fullmatch(args.lane):
        raise ValueError(f"Invalid lane name {args.lane!r}.")
    fields = {"lane": args.lane, **{key: str(value) for key, value in (section.get("inputs") or {}).items()}}
    for item in args.input or []:
        key, _, value = item.partition("=")
        fields[key] = value
    return dispatch_and_wait(section["repository"], section["workflow"], args.branch, fields, not args.no_wait,
                             args.timeout)


def websocket(args, cfg):
    section = deploy_config(cfg)["websocket"]
    if not WS_LANE.fullmatch(args.lane):
        raise ValueError(f"tsh-websocket lanes must look like ppe-…: {args.lane!r}.")
    result = dispatch_and_wait(section["repository"], section["workflow"], args.branch, {"lane": args.lane},
                               not args.no_wait, args.timeout)
    if not result["ok"]:
        result["hint"] = (f"新泳道需要先由人工运行 {section['infrastructure_workflow']}"
                          f"（environment_name={args.lane}）建好 WebSocket V2 基础设施；"
                          "失败日志里出现部署契约（deployment contract）或 IAM 角色相关错误即属此类。")
    return result


def web(args, cfg):
    section = deploy_config(cfg)["web"]
    result = dispatch_and_wait(section["repository"], section["workflow"], section.get("dispatch_ref") or "main",
                               {"branch": args.branch, "server_lane": args.server_lane or ""}, not args.no_wait,
                               args.timeout)
    result["preview_url"] = section["preview_url"].format(branch=args.branch)
    result["server_lane"] = args.server_lane or None
    return result


def computer(args, cfg):
    section = deploy_config(cfg)["computer"]
    result = dispatch_and_wait(section["repository"], section["workflow"], args.branch, {}, not args.no_wait,
                               args.timeout)
    if result["head_sha"]:
        result["canary_version"] = f"canary-{result['head_sha'][:12]}-{result['run_id']}-{result['attempt']}"
    return result


def destroy(args, cfg):
    config = deploy_config(cfg)
    prefix = config["server"]["lane_prefix"]
    if not LANE.fullmatch(args.lane) or not args.lane.startswith(prefix):
        raise ValueError(f"Only per-bug lanes ({prefix}*) can be destroyed here.")
    section = config[args.service]
    return dispatch_and_wait(section["repository"], section["destroy_workflow"], "main", {"lane": args.lane},
                             not args.no_wait, args.timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("fix-names", "server", "websocket", "web", "computer", "destroy-lane"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name == "fix-names":
            command.add_argument("--issue", required=True, help="Multica issue key, e.g. TES-123.")
            continue
        if name in ("server", "websocket", "web", "computer"):
            command.add_argument("--branch", required=True)
        if name in ("server", "websocket", "destroy-lane"):
            command.add_argument("--lane", required=True)
        if name == "destroy-lane":
            command.add_argument("--service", choices=("server", "websocket"), default="server")
        if name == "server":
            command.add_argument("--input", action="append", help="Extra workflow input key=value.")
        if name == "web":
            command.add_argument("--server-lane", help="Server PPE lane; empty uses the production backend.")
        command.add_argument("--no-wait", action="store_true", help="Dispatch only.")
        command.add_argument("--timeout", type=int, default=90, help="Minutes to wait for the run.")
    args = parser.parse_args()
    try:
        root = wb.data_root(args)
        cfg = wb.load_config(args, root)
        if args.operation == "fix-names":
            wb.emit({"ok": True, **fix_names(cfg, args.issue)})
            return 0
        result = {"server": server, "websocket": websocket, "web": web, "computer": computer,
                  "destroy-lane": destroy}[args.operation](args, cfg)
        if result["ok"] and access_url(args.operation, result):
            result["access_url"] = access_url(args.operation, result)
        wb.emit(result)
        return 0 if result["ok"] or args.no_wait else 1
    except (ValueError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
