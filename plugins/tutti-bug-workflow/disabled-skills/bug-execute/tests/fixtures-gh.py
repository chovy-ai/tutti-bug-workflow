#!/usr/bin/env python3
"""Fake gh for workflow dispatch: logs calls, prints a run URL, reports FAKE_GH_CONCLUSION."""

import json
import os
from pathlib import Path
import sys

log = Path(os.environ["FAKE_GH_LOG"])
calls = json.loads(log.read_text()) if log.exists() else []
calls.append(sys.argv[1:])
log.write_text(json.dumps(calls))
args = sys.argv[1:]
if args[:2] == ["workflow", "run"]:
    run_id = 1000 + len([c for c in calls if c[:2] == ["workflow", "run"]])
    repo = args[args.index("-R") + 1]
    if os.environ.get("FAKE_GH_NO_URL"):
        print("✓ Created workflow_dispatch event")
    else:
        print(f"https://github.com/{repo}/actions/runs/{run_id}")
elif args[:2] == ["run", "list"]:
    print(json.dumps([{"databaseId": 4242, "createdAt": "2999-01-01T00:00:00Z"}]))
elif args[:2] == ["run", "watch"]:
    sys.exit(0 if os.environ.get("FAKE_GH_CONCLUSION", "success") == "success" else 1)
elif args[:2] == ["run", "view"] and "--log-failed" in args:
    print("deploy\tRead contract\terror: v2 deployment contract not found for lane")
elif args[:2] == ["run", "view"]:
    run_id = args[2]
    print(json.dumps({"status": "completed", "conclusion": os.environ.get("FAKE_GH_CONCLUSION", "success"),
                      "url": f"https://github.com/x/actions/runs/{run_id}", "headSha": "abcdef1234567890ff",
                      "attempt": 1, "displayTitle": "t"}))
else:
    print(f"unsupported {args}", file=sys.stderr)
    sys.exit(1)
