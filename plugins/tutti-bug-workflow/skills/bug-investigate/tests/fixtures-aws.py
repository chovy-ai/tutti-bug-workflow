#!/usr/bin/env python3
"""Fake `aws logs start-query/get-query-results`; rows from FAKE_AWS_ROWS, state in FAKE_AWS_STATE."""
import json, os, re, sys
from pathlib import Path
args = sys.argv[1:]
state_path = Path(os.environ["FAKE_AWS_STATE"])
state = json.loads(state_path.read_text()) if state_path.exists() else {"queries": []}
if args[:2] == ["sso", "login"]:
    state["logged_in"] = os.environ.get("FAKE_AWS_LOGIN") != "fail"
    state_path.write_text(json.dumps(state))
    sys.exit(0 if state["logged_in"] else 1)
if os.environ.get("FAKE_AWS_EXPIRED") and not state.get("logged_in"):
    print("Error when retrieving token from sso: Token has expired and refresh failed", file=sys.stderr); sys.exit(255)
if os.environ.get("FAKE_AWS_FAIL"):
    print("AccessDenied", file=sys.stderr); sys.exit(255)
if "start-query" in args:
    query = args[args.index("--query-string") + 1]
    state["queries"].append(query)
    state_path.write_text(json.dumps(state))
    print(json.dumps({"queryId": f"q{len(state['queries'])}"})); sys.exit(0)
query = state["queries"][int(args[args.index("--query-id") + 1][1:]) - 1]
terms = re.findall(r'log like "([^"]+)"', query)
rows = [r for r in json.loads(os.environ.get("FAKE_AWS_ROWS", "[]")) if any(t in r["log"] for t in terms)]
print(json.dumps({"status": "Complete", "results": [[{"field": k, "value": v} for k, v in r.items()] for r in rows]}))
