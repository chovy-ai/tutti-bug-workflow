#!/usr/bin/env python3
"""Local Bug dossier helpers for this skill: create a dossier, hash reports, check execution handoff.

Standard library only. Templates come from this skill's assets/.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from datetime import datetime

SKILL_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = SKILL_ROOT.parents[1]
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
ARTIFACTS = ("analysis.md", "plan.md", "acceptance.md")


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".workbench-", delete=False) as stream:
            temp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temp.replace(path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def data_root(args):
    selected = (args.data_dir or os.environ.get("BUG_WORKBENCH_DATA")
                or os.environ.get("PLUGIN_DATA")
                or str(Path.home() / ".local/share/bug-workbench"))
    path = Path(selected).expanduser().resolve()
    if path == PLUGIN_ROOT or PLUGIN_ROOT in path.parents:
        raise ValueError("Keep runtime data outside the plugin source/cache.")
    return path


def bug_directory(root, bug_id):
    if not NAME.fullmatch(bug_id):
        raise ValueError("Bug ID must use 1-64 letters, digits, hyphens or underscores.")
    directory = (root / "bugs" / bug_id).resolve()
    if root not in directory.parents:
        raise ValueError("Bug path escapes data directory.")
    return directory


def new_bug(args, root):
    directory = bug_directory(root, args.bug_id)
    if directory.exists():
        emit({"bug_dir": str(directory), "action": "preserved"})
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".new-bug-", dir=directory.parent))
    try:
        dossier = read_json(SKILL_ROOT / "assets/bug.json")
        dossier["bug_id"] = args.bug_id
        dossier["source_url"] = args.source_url
        write_json(temporary / "bug.json", dossier)
        for name in (*ARTIFACTS, "verification.md"):
            shutil.copyfile(SKILL_ROOT / "assets" / name, temporary / name)
        (temporary / "dialogue.jsonl").touch()
        (temporary / "evidence").mkdir()
        temporary.rename(directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    emit({"bug_dir": str(directory), "action": "created", "status": "pending_analysis"})


def artifact_hashes(directory):
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in ARTIFACTS}


def positive_int(value):
    return type(value) is int and value > 0


def execution_errors(directory, expected_id):
    bug = read_json(directory / "bug.json")
    errors = []
    if bug.get("bug_id") != expected_id:
        errors.append("Bug ID differs from the requested dossier.")
    if not positive_int(bug.get("input_revision")):
        errors.append("QA input must have a positive revision.")
    if bug.get("pending_questions"):
        errors.append("Outstanding context questions must be resolved first.")
    root = bug.get("root_cause", {})
    plan = bug.get("plan", {})
    acceptance = bug.get("acceptance", {})
    if root.get("status") != "confirmed" or not positive_int(root.get("version")):
        errors.append("Root cause is not confirmed and versioned.")
    if root.get("input_revision") != bug.get("input_revision"):
        errors.append("Root cause does not cover the latest QA input.")
    if plan.get("status") != "approved" or not positive_int(plan.get("version")):
        errors.append("Plan is not marked approved and versioned.")
    if plan.get("root_cause_version") != root.get("version"):
        errors.append("Plan references a different root-cause version.")
    if (not positive_int(acceptance.get("version"))
            or acceptance.get("plan_version") != plan.get("version")):
        errors.append("Acceptance criteria are missing or reference a different plan.")
    baselines = bug.get("baselines")
    if (not isinstance(baselines, dict) or not baselines
            or not all(NAME.fullmatch(key) and isinstance(value, str) and SHA.fullmatch(value)
                       for key, value in baselines.items())):
        errors.append("Record full commit SHAs for all relevant repository baselines.")
    approval_path = directory / "approval.json"
    if not approval_path.is_file():
        errors.append("A real RD approval receipt is required.")
        return errors
    approval = read_json(approval_path)
    bindings = {"bug_id": expected_id, "input_revision": bug.get("input_revision"),
                "root_cause_version": root.get("version"), "plan_version": plan.get("version"),
                "acceptance_version": acceptance.get("version"), "baselines": baselines}
    if approval.get("decision") != "approved":
        errors.append("RD did not approve execution.")
    for key, value in bindings.items():
        if approval.get(key) != value:
            errors.append(f"Approval binding is stale: {key}.")
    actor = approval.get("actor", {})
    source = approval.get("source", {})
    if not isinstance(actor, dict) or actor.get("role") != "RD" or not actor.get("id"):
        errors.append("RD actor reference is missing.")
    if (not isinstance(source, dict) or source.get("kind") not in {"feishu_record", "codex_user_message"}
            or not source.get("reference")):
        errors.append("Original approval source is missing.")
    try:
        approved_at = datetime.fromisoformat(str(approval.get("approved_at", "")).replace("Z", "+00:00"))
        if approved_at.tzinfo is None:
            raise ValueError("Timezone is missing.")
    except ValueError:
        errors.append("Approval timestamp must include a timezone.")
    if approval.get("artifact_sha256") != artifact_hashes(directory):
        errors.append("Reports changed after approval or their SHA-256 values are missing.")
    return errors


def check_execution(args, root):
    directory = bug_directory(root, args.bug_id)
    errors = execution_errors(directory, args.bug_id)
    emit({"consistent": not errors, "errors": errors,
          "approval_identity_verified": False,
          "next_action": "Verify original RD approval and actual Git baselines before editing."
                         if not errors else "Resolve handoff inconsistencies before execution."})
    return 2 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("new-bug", "artifact-hashes", "check-execution"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--bug-id", required=True)
        if name == "new-bug":
            command.add_argument("--source-url")
    args = parser.parse_args()
    try:
        root = data_root(args)
        if args.operation == "new-bug":
            return new_bug(args, root) or 0
        if args.operation == "artifact-hashes":
            emit({"artifact_sha256": artifact_hashes(bug_directory(root, args.bug_id))})
            return 0
        return check_execution(args, root)
    except (ValueError, OSError, TypeError) as error:
        emit({"ok": False, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
