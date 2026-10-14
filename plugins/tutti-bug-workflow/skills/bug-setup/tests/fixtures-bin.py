#!/usr/bin/env python3
"""Fake CLIs for prepare.py, dispatched on the executable name; behavior from FAKE_TOOLS (JSON)."""

import json
import os
from pathlib import Path
import shutil
import sys

name = Path(sys.argv[0]).name
args = sys.argv[1:]
tools = json.loads(os.environ.get("FAKE_TOOLS", "{}"))
log = Path(os.environ["FAKE_TOOLS_LOG"])
log.write_text(log.read_text() + json.dumps([name, *args]) + "\n" if log.exists() else json.dumps([name, *args]) + "\n")
PACKAGES = {"@larksuite/cli": "lark-cli", "@openai/codex": "codex", "@mermaid-js/mermaid-cli": "mmdc",
            "@tutti-os/tutti-ops-cli": "tutti-ops", "@tutti-os/tutti-cli": "tutti-cli"}


def out(value):
    print(json.dumps(value) if not isinstance(value, str) else value)
    sys.exit(0)


if name == "node":
    out(tools.get("node", "v22.1.0"))
if name == "npm":
    if args[:2] == ["install", "-g"]:
        target = Path(sys.argv[0]).parent / PACKAGES[args[2]]
        shutil.copyfile(__file__, target)
        target.chmod(0o755)
        out("added 1 package")
    if args[:2] == ["prefix", "-g"]:
        out(str(Path(sys.argv[0]).parent.parent))
if name == "lark-cli":
    if args[:2] == ["auth", "status"]:
        logged = tools.get("lark_logged_in", True)
        out({"appId": "cli_x", "identities": {"user": {"tokenStatus": "valid" if logged else "expired",
                                                       "userName": "韦超", "openId": "ou_me",
                                                       "message": "ok" if logged else "User token expired"}}})
    if args[:2] == ["base", "+field-list"]:
        out({"ok": True, "data": {"fields": [{"field_id": f} for f in tools.get("fields", [])]}})
if name == "git":
    if args[0] == "ls-remote":
        out("abc\trefs/heads/main")
    if args[0] == "config":
        sys.exit(0 if tools.get("git_helper", True) else 1)
if name == "codex" and args[:2] == ["login", "status"]:
    out("Logged in using ChatGPT")
if name == "mmdc":
    Path(args[args.index("-o") + 1]).write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    out("")
if name == "gh":
    if args[:2] == ["auth", "status"]:
        out(f"Logged in to github.com account tester (keyring)\n  - Token scopes: {tools.get('gh_scopes', chr(39) + 'repo' + chr(39))}")
    if args[:2] == ["auth", "setup-git"]:
        out("")
    if args[0] == "api":
        out("true" if args[1].rsplit("/", 1)[1] in tools.get("push", []) else "false")
if name == "tutti-ops":
    if "auth" in args:
        out({"ok": tools.get("tutti_token", True)})
    if args[:2] == ["computer", "--help"]:
        out("computer commands")
if name == "tutti-cli":
    if args == ["--help"]:
        out("Tutti CLI — account login and Room Tasks\n  tutti-cli login [--no-browser] [--json]")
    if args[:1] == ["whoami"]:
        if tools.get("tutti_cli_logged_in", True):
            out({"userId": "1", "name": "QA", "email": "qa@example.com"})
        print("tutti-cli: No readable CLI session; run tutti-cli login", file=sys.stderr)
        sys.exit(1)
print(f"unsupported {name} {args}", file=sys.stderr)
sys.exit(1)
