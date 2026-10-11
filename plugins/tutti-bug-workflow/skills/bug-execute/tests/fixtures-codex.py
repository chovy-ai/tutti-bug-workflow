#!/usr/bin/env python3
"""Fake `codex exec`: records its arguments and prompt, and hands chosen records over for review."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys

prompt = sys.stdin.read()
record_id = re.search(r"record_id：(\S+)", prompt).group(1)
log = Path(os.environ["FAKE_CODEX_LOG"])
calls = json.loads(log.read_text()) if log.exists() else []
calls.append({"argv": sys.argv[1:], "prompt": prompt, "cwd": os.getcwd()})
log.write_text(json.dumps(calls, ensure_ascii=False))
if record_id in os.environ.get("FAKE_CODEX_ANALYSE", "").split(","):
    state_path = Path(os.environ["FAKE_LARK_STATE"])
    state = json.loads(state_path.read_text())
    state["records"][record_id][os.environ["FAKE_PLAN_FIELD"]] = os.environ.get("FAKE_PLAN_VALUE", "待评审")
    state_path.write_text(json.dumps(state))
if record_id in os.environ.get("FAKE_CODEX_DEPLOY", "").split(","):
    # Deploy the way a session does, without --record-id: the round's environment supplies it.
    deploy = Path(__file__).resolve().parents[1] / "scripts/deploy.py"
    subprocess.run([sys.executable, str(deploy), "web", "--branch", f"codex/bug-{record_id.lower()}",
                    "--server-lane", f"ppe-bug-{record_id.lower()}"], check=True, capture_output=True)
    subprocess.run([sys.executable, str(deploy), "server", "--branch", f"codex/bug-{record_id.lower()}",
                    "--lane", f"ppe-bug-{record_id.lower()}"], check=True, capture_output=True)
    if os.environ.get("FAKE_CODEX_CLEAR_ENVIRONMENT"):  # e.g. the session overwrote the column
        state_path = Path(os.environ["FAKE_LARK_STATE"])
        state = json.loads(state_path.read_text())
        state["records"][record_id].pop(os.environ["FAKE_ENVIRONMENT_FIELD"], None)
        state_path.write_text(json.dumps(state))
print("done")
