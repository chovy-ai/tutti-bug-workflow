#!/usr/bin/env python3
"""Fake `multica` CLI backed by a JSON state file (FAKE_MULTICA_STATE); logs every call."""

import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

state_path = Path(os.environ["FAKE_MULTICA_STATE"])
state = json.loads(state_path.read_text())
args = sys.argv[1:]
state.setdefault("calls", []).append(args)


def option(name, default=None):
    return args[args.index(name) + 1] if name in args else default


def done(value=None, table=None):
    state_path.write_text(json.dumps(state, ensure_ascii=False))
    if table is not None:
        print(table)
    elif value is not None:
        print(json.dumps(value, ensure_ascii=False))
    sys.exit(0)


def fail(message):
    state_path.write_text(json.dumps(state, ensure_ascii=False))
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


if option("--profile") != state.get("profile", "desktop-api.multica.ai") or not state.get("logged_in", True):
    fail("not authenticated: run 'multica login' first")
words = [arg for index, arg in enumerate(args)
         if not arg.startswith("--") and (index == 0 or not args[index - 1].startswith("--"))]
if words[:2] == ["workspace", "list"]:
    if state.get("cli") != "legacy":
        done([{"id": entry["id"], "name": entry["name"]} for entry in state["workspaces"]])
    done(table="ID                                    NAME\n" + "\n".join(
        f"{entry['id']}  {entry['name']}" for entry in state["workspaces"]))
if option("--workspace-id") not in {entry["id"] for entry in state["workspaces"]}:
    fail("workspace_id is required")
skills = {entry["id"]: entry for entry in state["skills"]}
agents = {entry["id"]: entry for entry in state["agents"]}
match words[:3]:
    case ["agent", "list", *_]:
        done(state["agents"])
    case ["runtime", "list", *_]:
        done(state["runtimes"])
    case ["project", "list", *_]:
        done(state["projects"])
    case ["skill", "list", *_]:
        done([{k: v for k, v in entry.items() if k not in ("content", "files")} for entry in state["skills"]])
    case ["skill", "get", skill_id]:
        if state.get("cli") == "legacy":
            done(skills[skill_id])
        digest = lambda entry: {**{k: v for k, v in entry.items() if k != "content"},  # noqa: E731
                                "content_hash": hashlib.sha256(entry["content"].encode()).hexdigest()}
        done({**digest(skills[skill_id]), "files": [digest(f) for f in skills[skill_id]["files"]]})
    case ["skill", "create", *_]:
        entry = {"id": str(uuid.uuid4()), "name": option("--name"), "content": option("--content"),
                 "description": option("--description"), "files": []}
        state["skills"].append(entry)
        done(entry)
    case ["skill", "update", skill_id]:
        skills[skill_id].update(content=option("--content"), description=option("--description"))
        done(skills[skill_id])
    case ["skill", "delete", skill_id]:
        state["skills"] = [entry for entry in state["skills"] if entry["id"] != skill_id]
        done(table="deleted")
    case ["skill", "files", "upsert"]:
        skill = skills[words[3]]
        current = next((f for f in skill["files"] if f["path"] == option("--path")), None)
        if current:
            current["content"] = option("--content")
        else:
            skill["files"].append({"id": str(uuid.uuid4()), "path": option("--path"), "content": option("--content")})
        done({"ok": True})
    case ["skill", "files", "delete"]:
        skill = skills[words[3]]
        skill["files"] = [f for f in skill["files"] if f["id"] != words[4]]
        done(table="deleted")
    case ["agent", "skills", "set"]:
        agents[words[3]]["skills"] = [{"id": i, "name": skills[i]["name"], "enabled": True}
                                      for i in option("--skill-ids").split(",")]
        done(agents[words[3]]["skills"])
    case ["agent", "update", agent_id]:
        agents[agent_id]["instructions"] = option("--instructions")
        done(agents[agent_id])
fail(f"unsupported {args}")
