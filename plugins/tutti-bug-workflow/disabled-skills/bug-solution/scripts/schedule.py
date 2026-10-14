#!/usr/bin/env python3
"""Install, list, remove or trigger the hourly root-cause analysis for one assignee (macOS launchd).

`install --assignee NAME [--min-priority P1]` resolves the person through the Feishu
address book (no name means the logged-in user) and writes a user LaunchAgent that runs
scan.py every interval_seconds. One job per assignee, so a machine can run several.
The job runs on this machine with the current PATH, so lark-cli, git, codex and mmdc
use their existing logins.
"""

import argparse
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import common as wb  # noqa: E402
import feishu  # noqa: E402
import scan  # noqa: E402

PREFIX = "com.tutti.bug-solution."


def agents_dir():
    return Path(os.environ.get("LAUNCH_AGENTS_DIR") or Path.home() / "Library/LaunchAgents")


def launchctl(*arguments, check=True):
    command = [os.environ.get("LAUNCHCTL") or "launchctl", *arguments]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
    if check and result.returncode:
        raise ValueError(f"launchctl {arguments[0]} failed: {(result.stderr or result.stdout).strip()}")
    return result


def domain():
    return f"gui/{os.getuid()}"


def label(open_id):
    return PREFIX + re.sub(r"[^A-Za-z0-9_-]", "_", open_id)


def resolve(client, name):
    user, chosen = client.resolve_user(name)
    if not user:
        wb.emit({"ok": False, "status": "ambiguous" if chosen else "not_found", "assignee": name,
                 "candidates": chosen})
        return None
    return user


def jobs():
    found = []
    for path in sorted(agents_dir().glob(PREFIX + "*.plist")):
        with path.open("rb") as stream:
            plist = plistlib.load(stream)
        arguments = plist.get("ProgramArguments", [])

        def flag(name):
            return arguments[arguments.index(name) + 1] if name in arguments else None
        found.append({"label": plist.get("Label"), "plist": str(path), "assignee_open_id": flag("--assignee"),
                      "assignee": plist.get("EnvironmentVariables", {}).get("BUG_SOLUTION_ASSIGNEE"),
                      "min_priority": flag("--min-priority"), "interval_seconds": plist.get("StartInterval"),
                      "log": plist.get("StandardOutPath")})
    return found


def install(args, root, cfg, client):
    user = resolve(client, args.assignee)
    if not user:
        return 1
    interval = args.interval or scan.schedule_config(cfg)["interval_seconds"]
    name = label(user["open_id"])
    logs = root / "solution-runs/logs"
    logs.mkdir(parents=True, exist_ok=True)
    arguments = [sys.executable, str(SCRIPTS / "scan.py"), "--assignee", user["open_id"], "--data-dir", str(root)]
    if args.config:
        arguments += ["--config", str(Path(args.config).expanduser().resolve())]
    if args.min_priority:
        arguments += ["--min-priority", args.min_priority]
    plist = {"Label": name, "ProgramArguments": arguments, "StartInterval": int(interval),
             "RunAtLoad": bool(args.run_now), "WorkingDirectory": str(root),
             "StandardOutPath": str(logs / f"{name}.log"), "StandardErrorPath": str(logs / f"{name}.log"),
             "EnvironmentVariables": {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                      "HOME": str(Path.home()), "BUG_WORKBENCH_DATA": str(root),
                                      "BUG_SOLUTION_ASSIGNEE": user["name"] or user["open_id"]}}
    path = agents_dir() / f"{name}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    launchctl("bootout", f"{domain()}/{name}", check=False)  # replace an existing job
    with path.open("wb") as stream:
        plistlib.dump(plist, stream)
    launchctl("bootstrap", domain(), str(path))
    wb.emit({"ok": True, "action": "installed", "assignee": user, "label": name, "plist": str(path),
             "interval_seconds": int(interval), "min_priority": args.min_priority,
             "log": plist["StandardOutPath"], "runs_now": bool(args.run_now)})
    return 0


def find_job(client, assignee):
    current = jobs()
    if assignee and assignee.startswith("ou_"):
        matched = [job for job in current if job["assignee_open_id"] == assignee]
    else:
        user = resolve(client, assignee)
        if not user:
            return None
        matched = [job for job in current if job["assignee_open_id"] == user["open_id"]]
    if not matched:
        wb.emit({"ok": False, "error": f"No scheduled analysis for {assignee or '当前用户'}.", "jobs": current})
        return None
    return matched[0]


def uninstall(args, root, cfg, client):
    job = find_job(client, args.assignee)
    if not job:
        return 1
    launchctl("bootout", f"{domain()}/{job['label']}", check=False)
    Path(job["plist"]).unlink(missing_ok=True)
    wb.emit({"ok": True, "action": "uninstalled", **job})
    return 0


def run_now(args, root, cfg, client):
    job = find_job(client, args.assignee)
    if not job:
        return 1
    launchctl("kickstart", f"{domain()}/{job['label']}")
    wb.emit({"ok": True, "action": "started", **job})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("install", "list", "uninstall", "run-now"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name != "list":
            command.add_argument("--assignee", help="跟进人姓名或 open_id；缺省为当前登录用户。")
        if name == "install":
            command.add_argument("--min-priority", choices=feishu.PRIORITIES, help="只分析该优先级及以上。")
            command.add_argument("--interval", type=int, help="Seconds between rounds; default from config.")
            command.add_argument("--run-now", action="store_true", help="Also start a round right away.")
    args = parser.parse_args()
    try:
        if args.operation == "list":
            wb.emit({"ok": True, "jobs": jobs()})
            return 0
        root = wb.data_root(args)
        cfg = wb.load_config(args, root)
        client = feishu.Feishu(cfg)
        return {"install": install, "uninstall": uninstall, "run-now": run_now}[args.operation](
            args, root, cfg, client)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
