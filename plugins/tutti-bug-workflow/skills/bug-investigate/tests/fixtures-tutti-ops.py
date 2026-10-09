#!/usr/bin/env python3
"""Fake tutti-ops `computer log-recalls` and tutti-computer `status`, state in FAKE_OPS_STATE."""

import json
import os
from pathlib import Path
import sys

state_path = Path(os.environ["FAKE_OPS_STATE"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]


def out(data, ok=True):
    state_path.write_text(json.dumps(state))
    print(json.dumps({"ok": True, "data": data} if ok else {"ok": False, "error": {"message": data}}))
    sys.exit(0 if ok else 1)


if args[:1] == ["status"]:
    print(json.dumps({"computerId": state.get("local_computer_id")}))
    sys.exit(0)
words = [item for item in args if not item.startswith("--")]
operation = next(item for item in ("list", "get", "create", "download-url") if item in words)
state.setdefault("calls", []).append(operation)
if operation == "list":
    out({"items": state["tasks"]})
if operation == "create":
    if state.get("create_fails"):
        out("permission denied", ok=False)
    preset = args[args.index("--range-preset") + 1]
    task = {**state["new_task"], "taskId": "task-new", "rangePreset": int(preset)}
    state["tasks"].append(task)
    state["created_preset"] = int(preset)
    out(task)
task_id = args[args.index("--task-id") + 1]
task = next(item for item in state["tasks"] if item["taskId"] == task_id)
if operation == "get":
    progress = state.get("progress", [])
    if progress:
        task.update(progress.pop(0))
    out(task)
out({"downloadUrl": Path(state["package"]).as_uri(), "fileName": "Dev's Mac_logs.tar.gz"})
