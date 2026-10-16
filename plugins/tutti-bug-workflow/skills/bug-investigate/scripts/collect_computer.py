#!/usr/bin/env python3
"""Collect Computer runtime logs for one incident; standard library only.

Stateless: inputs come from arguments, the result is one JSON object on stdout,
and downloaded files are temporary working files for this session.

- Local: when `tutti-computer status --json` reports the target computerId, copy
  the configured `computer-local` log files and read each file's first and last
  timestamp. `captured` only when every configured file spans the whole incident
  window (10 minutes before to 5 after, capped by report time); otherwise `partial` with the coverage, so the caller can recall remotely (--source remote).
- Remote: reuse a downloadable or in-flight Tutti runtime-log recall that covers
  the incident, otherwise create one; wait until it finishes, download the
  package, verify its SHA-256 and extract it safely.

The result `status` is captured, partial or blocked; exit code 0 means a
result was produced (including blocked), 2 means invalid input.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as wb  # noqa: E402

DEFAULT_ADMIN_URL = "https://admin.tutti.sh"
LEAD = timedelta(minutes=10)  # Logs needed before the incident.
MARGIN = timedelta(minutes=5)  # Slack when choosing a recall range.
PRESETS = [(1, timedelta(hours=1)), (2, timedelta(hours=3)), (3, timedelta(days=1)),
           (4, timedelta(days=3)), (5, timedelta(days=14))]
STATES = {"WAITING_FOR_DEVICE": 1, "DEVICE_PROCESSING": 2, "DOWNLOADABLE": 3, "FAILED": 4}
TASK_FIELDS = ("taskId", "state", "rangePreset", "requestedStartAt", "requestedEndAt",
               "actualStartAt", "actualEndAt", "truncated", "unknownTimestampRows",
               "computerVersion", "sha256", "compressedBytes", "failureCode", "failureMessage",
               "deadlineAt", "downloadExpiresAt", "createdAt")


class Blocked(Exception):
    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = details


def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def state_of(task):
    value = task.get("state")
    if isinstance(value, int):
        return value
    name = str(value or "").removeprefix("COMPUTER_RUNTIME_LOG_RECALL_STATE_")
    return STATES.get(name, 0)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_entry(path):
    return {"path": str(path), "name": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)}


def command_for(cfg, name, env):
    if os.environ.get(env):
        return os.environ[env]
    return next((item["command"] for item in cfg.get("cli_dependencies", [])
                 if item.get("name") == name), name)


# ---------- local ----------

def local_computer_id(command):
    try:
        result = subprocess.run([command, "status", "--json"], capture_output=True, text=True,
                                timeout=30, check=False)
        return json.loads(result.stdout).get("computerId") if result.returncode == 0 else None
    except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
        return None


def local_paths(cfg):
    source = next((item for item in cfg.get("log_sources", []) if item.get("name") == "computer-local"), {})
    return source.get("paths") or []


STAMP = re.compile(rb"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})")
EDGE = 256 * 1024


def stamp_of(line):
    match = STAMP.search(line)
    if not match:
        return None
    try:
        return parse_time(match.group(0).decode())
    except ValueError:
        return None


def time_span(path):
    """First and last timestamp of a log, read from its first and last 256 KiB."""
    with path.open("rb") as handle:
        head = handle.read(EDGE)
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - EDGE))
        tail = handle.read()
    first = next((value for value in map(stamp_of, head.splitlines()) if value), None)
    last = next((value for value in map(stamp_of, reversed(tail.splitlines())) if value), None)
    return first, last


def collect_local(cfg, output, since, until):
    paths = local_paths(cfg)
    if not paths:
        raise Blocked("computer-local.paths is not configured")
    files, gaps = [], []
    for raw in paths:
        try:
            path = wb.resolve_log_path(raw)
        except ValueError as error:
            gaps.append(f"{raw}: {error}")
            continue
        if not path.is_file():
            gaps.append(f"{path}: not found")
            continue
        target = output / path.name
        shutil.copy2(path, target)
        entry = file_entry(target)
        first, last = time_span(target)
        entry["first_at"], entry["last_at"] = (iso(first) if first else None), (iso(last) if last else None)
        entry["coverage"] = ("unknown" if not (first and last) else
                             "full" if first <= since and last >= until else
                             "none" if last < since or first > until else "partial")
        files.append(entry)
    if not files:
        raise Blocked("none of the configured local log files exist", gaps=gaps)
    covering = [entry["name"] for entry in files if entry["coverage"] == "full"]
    if not covering:
        gaps.append(f"no local log spans {iso(since)}..{iso(until)} (rotated or not written then); "
                    "recall the logs remotely with --source remote")
    for entry in files:
        if entry["coverage"] != "full":
            gaps.append(f"{entry['name']}: coverage {entry['coverage']} "
                        f"({entry['first_at'] or '?'}..{entry['last_at'] or '?'})")
    if gaps and covering:
        gaps.append("local evidence is incomplete; recall the logs remotely with --source remote")
    return {"status": "partial" if gaps else "captured", "covering_files": covering,
            "files": files, "gaps": gaps}


# ---------- remote ----------

class TuttiOps:
    def __init__(self, command, admin_url):
        self.command = command
        self.admin_url = admin_url

    def run(self, mode, *arguments):
        command = [self.command, "--admin-url", self.admin_url, "--mode", mode, "--json", *arguments]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
        except FileNotFoundError:
            raise Blocked(f"tutti-ops not found: {self.command}") from None
        except subprocess.TimeoutExpired:
            raise Blocked(f"tutti-ops timed out: {' '.join(arguments[:3])}") from None
        try:
            value = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise Blocked(f"tutti-ops returned non-JSON (exit {result.returncode})",
                          stderr=(result.stderr or "").strip()[:500]) from None
        if result.returncode != 0 or value.get("ok") is not True:
            error = value.get("error") or {}
            raise Blocked(f"tutti-ops {' '.join(arguments[:3])} failed: "
                          f"{error.get('message') or error.get('code') or value}")
        return value.get("data") or {}

    def tasks(self, computer_id):
        data = self.run("read", "computer", "log-recalls", "list", "--computer-id", computer_id,
                        "--page-all", "--page-limit", "10")
        return data.get("items") or data.get("tasks") or []

    def get(self, computer_id, task_id):
        return self.run("read", "computer", "log-recalls", "get", "--computer-id", computer_id,
                        "--task-id", task_id)

    def create(self, computer_id, preset):
        return self.run("write", "computer", "log-recalls", "create", "--computer-id", computer_id,
                        "--range-preset", str(preset), "--yes")

    def download_url(self, computer_id, task_id):
        return self.run("read", "computer", "log-recalls", "download-url", "--computer-id", computer_id,
                        "--task-id", task_id)


def choose_preset(since, now):
    needed = now - since + MARGIN
    for preset, span in PRESETS:
        if span >= needed:
            return preset
    raise Blocked("incident is older than the 14-day recall range", needed_since=iso(since))


def covers(task, since, until, actual):
    start = parse_time(task.get("actualStartAt") if actual else None) or parse_time(task.get("requestedStartAt"))
    end = parse_time(task.get("actualEndAt") if actual else None) or parse_time(task.get("requestedEndAt"))
    return bool(start and end and start <= since and end >= until)


def pick_task(tasks, since, until, now):
    downloadable = [task for task in tasks if state_of(task) == 3 and not task.get("downloadExpired")
                    and covers(task, since, until, actual=True)]
    if downloadable:
        return max(downloadable, key=lambda task: task.get("createdAt") or ""), "reused"
    running = [task for task in tasks if state_of(task) in (1, 2) and covers(task, since, until, actual=False)
               and (parse_time(task.get("deadlineAt")) or now) > now]
    if running:
        return max(running, key=lambda task: task.get("createdAt") or ""), "joined"
    return None, None


def wait(ops, computer_id, task, timeout, poll):
    started = time.monotonic()
    while state_of(task) in (1, 2):
        deadline = parse_time(task.get("deadlineAt"))
        if deadline and datetime.now(timezone.utc) > deadline + timedelta(minutes=1):
            raise Blocked("recall passed its deadline; the Computer may be offline",
                          task=summary(task))
        if time.monotonic() - started > timeout:
            raise Blocked("timed out waiting for the recall", task=summary(task))
        time.sleep(poll)
        task = ops.get(computer_id, task["taskId"])
    if state_of(task) == 4:
        raise Blocked(f"recall failed: {task.get('failureCode') or 'unknown'} {task.get('failureMessage') or ''}".strip(),
                      task=summary(task))
    if state_of(task) != 3:
        raise Blocked(f"unexpected recall state {task.get('state')!r}", task=summary(task))
    return task


def summary(task):
    return {key: task.get(key) for key in TASK_FIELDS if key in task}


def safe_name(value, fallback):
    # Keep the server's name and extension, replacing characters such as the
    # apostrophe in device names ("Chovy's_MacBook_...tar.gz").
    name = re.sub(r"[^A-Za-z0-9._-]", "_", PurePosixPath(str(value or "")).name)[-200:]
    return name if name.strip("._") else fallback


def download(url, target):
    scheme = urlparse(url).scheme
    if scheme != "https" and not (scheme == "file" and os.environ.get("COLLECT_COMPUTER_ALLOW_FILE_URL")):
        raise Blocked(f"refusing non-HTTPS download URL scheme {scheme!r}")
    temporary = target.with_name(target.name + ".part")
    try:
        # static.tutti.sh rejects Python's default User-Agent with 403.
        request = Request(url, headers={"User-Agent": "tutti-bug-workflow/collect-computer"})
        with urlopen(request, timeout=300) as response, temporary.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        temporary.replace(target)
    except OSError as error:
        raise Blocked(f"download failed: {error}") from None
    finally:
        temporary.unlink(missing_ok=True)


def extract(package, destination):
    """Extract zip/tar safely; return None for other formats."""
    def inside(name):
        resolved = (destination / name).resolve()
        return resolved == destination.resolve() or destination.resolve() in resolved.parents
    if zipfile.is_zipfile(package):
        with zipfile.ZipFile(package) as archive:
            if not all(inside(name) for name in archive.namelist()):
                raise Blocked("package contains paths outside its directory")
            archive.extractall(destination)
    elif tarfile.is_tarfile(package):
        with tarfile.open(package) as archive:
            members = archive.getmembers()
            if not all(inside(member.name) and (member.isfile() or member.isdir()) for member in members):
                raise Blocked("package contains links or paths outside its directory")
            archive.extractall(destination, members=members)
    else:
        return None
    return str(destination)


def collect_remote(cfg, args, output, since, until):
    ops = TuttiOps(command_for(cfg, "tutti-ops", "TUTTI_OPS"), args.admin_url)
    now = datetime.now(timezone.utc)
    task, origin = pick_task(ops.tasks(args.computer_id), since, until, now)
    if task is None:
        if args.no_create:
            raise Blocked("no reusable recall covers the incident and --no-create was given")
        task, origin = ops.create(args.computer_id, choose_preset(since, now)), "created"
        if not task.get("taskId"):
            raise Blocked("create returned no taskId; list recalls before retrying to avoid duplicates")
    task = wait(ops, args.computer_id, task, args.timeout_minutes * 60, args.poll_seconds)
    link = ops.download_url(args.computer_id, task["taskId"])
    url = link.get("downloadUrl") or link.get("download_url")
    if not url:
        raise Blocked("download-url returned no URL", task=summary(task))
    package = output / safe_name(link.get("fileName") or link.get("file_name"), f"{task['taskId']}.pkg")
    download(url, package)
    digest = sha256_file(package)
    if task.get("sha256") and digest != task["sha256"].lower():
        package.unlink(missing_ok=True)
        raise Blocked("package SHA-256 does not match the recall task", expected=task["sha256"], actual=digest)
    gaps = []
    if not task.get("sha256"):
        gaps.append("recall task has no SHA-256; integrity not verified")
    if not covers(task, since, until, actual=True):
        gaps.append(f"actual coverage {task.get('actualStartAt')}..{task.get('actualEndAt')} "
                    f"does not span {iso(since)}..{iso(until)}")
    if task.get("truncated"):
        gaps.append("recall package is truncated")
    if str(task.get("unknownTimestampRows") or "0") != "0":
        gaps.append(f"{task['unknownTimestampRows']} rows have unknown timestamps")
    extracted = extract(package, output / (package.name.split(".")[0] + "-extracted"))
    status = "partial" if any(not gap.startswith("recall task has no") and "unknown timestamps" not in gap
                              for gap in gaps) else "captured"
    return {"status": status, "recall": origin, "task": summary(task), "files": [file_entry(package)],
            "extracted_dir": extracted, "gaps": gaps}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--computer-id", required=True)
    parser.add_argument("--incident-at", required=True, help="ISO 8601 with timezone.")
    parser.add_argument("--question-time", help="Report time (ISO 8601 with timezone); defaults to now.")
    parser.add_argument("--output-dir", required=True, help="Temporary directory for this session.")
    parser.add_argument("--source", choices=("auto", "local", "remote"), default="auto")
    parser.add_argument("--admin-url", default=DEFAULT_ADMIN_URL)
    parser.add_argument("--no-create", action="store_true", help="Only reuse existing recalls.")
    parser.add_argument("--timeout-minutes", type=float, default=30)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--data-dir")
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        incident = parse_time(args.incident_at)
        if incident is None or incident.tzinfo is None:
            raise ValueError("--incident-at must be ISO 8601 with a timezone.")
        reported = parse_time(args.question_time) if args.question_time else datetime.now(timezone.utc)
        if reported.tzinfo is None:
            raise ValueError("--question-time must be ISO 8601 with a timezone.")
        since = incident - LEAD
        until = min(reported, incident + MARGIN)
        output = Path(args.output_dir).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        cfg = wb.load_config(args, wb.data_root(args))
    except (ValueError, OSError) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    result = {"computer_id": args.computer_id, "incident_at": args.incident_at,
              "window": {"since": iso(since), "until": iso(until)}}
    try:
        source = args.source
        if source == "auto":
            local = local_computer_id(command_for(cfg, "tutti-computer", "TUTTI_COMPUTER"))
            source = "local" if local == args.computer_id and local_paths(cfg) else "remote"
        result["source"] = source
        result.update(collect_local(cfg, output, since, until) if source == "local"
                      else collect_remote(cfg, args, output, since, until))
    except Blocked as blocked:
        result.update({"status": "blocked", "reason": blocked.reason, **blocked.details})
    wb.emit(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
