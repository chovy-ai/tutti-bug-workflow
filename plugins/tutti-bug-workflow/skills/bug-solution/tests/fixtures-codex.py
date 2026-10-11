#!/usr/bin/env python3
"""Fake `codex exec`: records its arguments and prompt, and hands chosen records over for review."""

import json
import os
from pathlib import Path
import re
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
    state["records"][record_id][os.environ["FAKE_PLAN_FIELD"]] = "待评审"
    state_path.write_text(json.dumps(state))
print("done")
