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
PACKAGES = {"@tutti-os/tutti-ops-cli": "tutti-ops", "@tutti-os/tutti-cli": "tutti-cli"}


def out(value):
    print(json.dumps(value) if not isinstance(value, str) else value)
    sys.exit(0)


if name == "node":
    out(tools.get("node", "v22.1.0"))
if name == "npm":
    if args[:2] == ["install", "-g"]:
        package = args[2].removesuffix("@latest")
        target = Path(sys.argv[0]).parent / PACKAGES[package]
        shutil.copyfile(__file__, target)
        target.chmod(0o755)
        if package == "@tutti-os/tutti-cli":
            (target.parent / ".tutti-cli-version").write_text(tools.get("tutti_cli_latest", "0.1.0"))
        out("added 1 package")
    if args[:2] == ["view", "@tutti-os/tutti-cli"]:
        if tools.get("npm_offline"):
            sys.exit(1)
        out(tools.get("tutti_cli_latest", "0.1.0"))
    if args[:2] == ["prefix", "-g"]:
        out(str(Path(sys.argv[0]).parent.parent))
if name == "git":
    if args[0] == "ls-remote":
        out("abc\trefs/heads/main")
    if args[0] == "config":
        sys.exit(0 if tools.get("git_helper", True) else 1)
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
        out("Tutti CLI — account login, Rooms and Tasks\n  tutti-cli login [--no-browser] [--json]\n"
            + ("  tutti-cli room list [--type all|local|cloud] [--json]\n"
               "  tutti-cli task comment --room-id ID --task-id UUID\n"
               "                  (--content TEXT | --content-file PATH|-)\n"
               + ("                  [--file PATH] [--room-file /room/PATH] [--json]\n"
                  if tools.get("tutti_cli_comment_files", True) else "                  [--json]\n")
               + "  tutti-cli task run --room-id ID --task-id UUID\n"
               "                  [--file PATH] [--room-file /room/PATH] [--json]\n"
               if tools.get("tutti_cli_rooms", True) else ""))
    if args == ["--version"]:
        marker = Path(sys.argv[0]).parent / ".tutti-cli-version"
        out(marker.read_text() if marker.exists() else tools.get("tutti_cli_version", "0.1.0"))
    if args[:1] == ["whoami"]:
        if tools.get("tutti_cli_logged_in", True):
            out({"userId": "1", "name": "QA", "email": "qa@example.com"})
        print("tutti-cli: No readable CLI session; run tutti-cli login", file=sys.stderr)
        sys.exit(1)
print(f"unsupported {name} {args}", file=sys.stderr)
sys.exit(1)
