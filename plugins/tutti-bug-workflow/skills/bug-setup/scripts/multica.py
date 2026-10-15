#!/usr/bin/env python3
"""Connect the workflow to the local Multica: one agent per role, Multica issues as the bug record.

The `multica` section of the workbench config names the CLI profile, the workspace, the
bug project and the three agents:

- `investigate` (bug-investigate): logs the bug on a Multica issue, then hands it to `analyze`.
- `analyze` (bug-analyze): root cause and fix plan on the issue, then `in_review` for the RD.
- `execute` (bug-execute): the RD assigns the approved issue; fix, PPE, self-check, report.

- `status`: read-only. CLI and login, workspace, project, each agent and its runtime, and
  whether the workspace copy of every skill matches this plugin source.
- `sync`: make the workspace match the source: create or update the three skills and their
  files (delete files the source no longer has), give each agent exactly its skill, and set
  the agent instructions that carry the hand-off. `--prune` also deletes the listed legacy
  workspace skills once no agent uses them.

Agents and the project are created by the person in Multica; sync never creates them.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workbench as wb  # noqa: E402

ROLES = {"investigate": "bug-investigate", "analyze": "bug-analyze", "execute": "bug-execute"}
LEGACY_SKILLS = ("bug-solution",)
MINIMUM_CLI = (0, 6, 0)  # issue create --description-file, --allow-external-file for attachments
SKIPPED = {"tests", "__pycache__"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
INSTRUCTIONS = {
    "investigate": ("你是 Tutti 的 Bug 守门员。收到分配给你的 issue 或消息后，按 bug-investigate 技能登记这条 Bug："
                    "Multica issue 是这条 Bug 的唯一记录，现场带全后把 issue 交给「{analyze}」分析根因。"
                    "自己不分析根因、不改代码。"),
    "analyze": ("你是 Tutti 的 Bug 分析师。issue 分配给你后，按 bug-analyze 技能拉最新代码分析根因、给出修复方案，"
                "回复在 issue 评论里，把状态置为 in_review 等 RD 评审。RD 在评论里追问或要求修改时，在同一个 issue 里补充。"
                "不改业务代码；RD 认可后会把 issue 分配给「{execute}」修复。"),
    "execute": ("你是 Tutti 的 Bug 解决专员。issue 分配给你后，按 bug-execute 技能依据 issue 里 RD 认可的方案修复、"
                "提 PR、部署 PPE、自验证，把结果和验证截图回复到 issue。没有 RD 认可的方案就停下来在 issue 里说明。"),
}


def settings(root):
    path = root / "config.json"
    config = wb.read_json(path) if path.is_file() else {}
    defaults = wb.read_json(wb.PLUGIN_ROOT / "config/workbench.example.json")["multica"]
    current = {**defaults, **(config.get("multica") or {})}
    current["agents"] = {**defaults["agents"], **(current.get("agents") or {})}
    return current


class Multica:
    def __init__(self, profile, workspace_id=None):
        self.profile, self.workspace_id = profile, workspace_id

    def run(self, *args, workspace=True, data=True):
        command = [shutil.which("multica") or "multica", "--profile", self.profile]
        if workspace:
            command += ["--workspace-id", self.workspace_id]
        command += [str(arg) for arg in args]
        if data:
            command += ["--output", "json"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False,
                                    env={key: value for key, value in os.environ.items()
                                         if not key.startswith("MULTICA_")})
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError(f"multica {' '.join(map(str, args))}: {error}") from None
        if result.returncode:
            raise ValueError(f"multica {' '.join(map(str, args))}: {(result.stderr or result.stdout).strip()[-400:]}")
        return json.loads(result.stdout) if data and result.stdout.strip() else result.stdout

    def workspaces(self):
        try:
            return [{"id": entry["id"], "name": entry["name"]}
                    for entry in self.run("workspace", "list", workspace=False)]
        except (ValueError, KeyError, TypeError):
            pass
        # CLIs before 0.6 only print a table with full IDs: ID and NAME columns.
        rows = []
        for line in self.run("workspace", "list", workspace=False, data=False).splitlines():
            match = UUID.match(line.strip())
            if match:
                rows.append({"id": match[0], "name": line.strip()[len(match[0]):].strip()})
        return rows


def same(remote, text):
    """Older CLIs return the text itself, 0.6+ only its sha256."""
    if "content" in remote:
        return remote["content"] == text
    return remote.get("content_hash") == hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_skill(name):
    folder = wb.PLUGIN_ROOT / "skills" / name
    content = (folder / "SKILL.md").read_text(encoding="utf-8")
    description = re.search(r"^description:\s*(.+)$", content, re.M)
    files, skipped = {}, []
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if not path.is_file() or relative.parts[0] in SKIPPED or "__pycache__" in relative.parts \
                or relative.as_posix() == "SKILL.md":
            continue
        try:
            files[relative.as_posix()] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped.append(relative.as_posix())  # skill files are text; images stay in the plugin only
    return {"name": name, "content": content, "description": description[1].strip() if description else "",
            "files": files, "skipped": skipped}


def cli_version():
    try:
        output = subprocess.run([shutil.which("multica"), "version"], capture_output=True, text=True,
                                timeout=30, check=False).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", output)
    return tuple(map(int, match.groups())) if match else None


def connect(cfg):
    if not shutil.which("multica"):
        raise ValueError("multica 未安装：先安装 Multica 桌面端或 CLI（brew install multica-ai/tap/multica）")
    version = cli_version()
    if version and version < MINIMUM_CLI:
        raise ValueError(f"{shutil.which('multica')} 是 {'.'.join(map(str, version))}，低于 "
                         f"{'.'.join(map(str, MINIMUM_CLI))}（没有 --allow-external-file 等参数，Agent 建 issue、"
                         "传附件会失败）：brew upgrade multica，或删掉它让 PATH 用 Multica 桌面端自带的 CLI")
    client = Multica(cfg["profile"])
    try:
        workspaces = client.workspaces()
    except ValueError as error:
        raise ValueError(f"Multica profile {cfg['profile']} 未登录或不可用：{error}") from None
    wanted = cfg.get("workspace_id")
    if wanted:
        if not any(entry["id"] == wanted for entry in workspaces):
            raise ValueError(f"profile {cfg['profile']} 里没有 workspace {wanted}；可用：{workspaces}")
    elif len(workspaces) == 1:
        wanted = workspaces[0]["id"]
    else:
        raise ValueError(f"profile {cfg['profile']} 有 {len(workspaces)} 个 workspace，请在配置 multica.workspace_id 指定：{workspaces}")
    client.workspace_id = wanted
    return client


def inspect(cfg, client):
    agents = {entry["name"]: entry for entry in client.run("agent", "list")}
    runtimes = {entry["id"]: entry for entry in client.run("runtime", "list")}
    skills = {entry["name"]: entry for entry in client.run("skill", "list")}
    projects = client.run("project", "list")
    project = next((p for p in projects if cfg["project"] in (p.get("title"), p.get("id"))), None)
    roles = {}
    for role, skill in ROLES.items():
        name = cfg["agents"][role]
        agent = agents.get(name)
        entry = {"agent": name, "skill": skill}
        if not agent:
            entry["problem"] = "agent 不存在"
        else:
            runtime = runtimes.get(agent.get("runtime_id")) or {}
            assigned = sorted(s["name"] for s in agent.get("skills") or [] if s.get("enabled", True))
            entry.update(id=agent["id"], runtime=runtime.get("name"), runtime_status=runtime.get("status"),
                         assigned=assigned, instructions_current=agent.get("instructions") == instructions(cfg, role))
            if runtime.get("status") != "online":
                entry["problem"] = f"runtime 不在线：{runtime.get('name') or agent.get('runtime_id')}"
        roles[role] = entry
    drift = {}
    for skill in ROLES.values():
        source = source_skill(skill)
        remote = skills.get(skill)
        if not remote:
            drift[skill] = "missing"
            continue
        detail = client.run("skill", "get", remote["id"])
        remote_files = {f["path"]: f for f in detail.get("files") or []}
        changed = sorted(p for p, text in source["files"].items() if not same(remote_files.get(p) or {}, text))
        stale = sorted(set(remote_files) - set(source["files"]))
        if not same(detail, source["content"]) or detail.get("description") != source["description"]:
            changed.insert(0, "SKILL.md")
        drift[skill] = {"changed": changed, "stale": stale} if changed or stale else "ok"
    return {"workspace_id": client.workspace_id, "project": project and {"id": project["id"], "title": project["title"]},
            "agents": roles, "skills": drift, "legacy_skills": sorted(set(LEGACY_SKILLS) & set(skills))}


def instructions(cfg, role):
    return INSTRUCTIONS[role].format(**cfg["agents"])


def sync(cfg, client, prune):
    done = []
    skills = {entry["name"]: entry for entry in client.run("skill", "list")}
    ids = {}
    for skill in ROLES.values():
        source = source_skill(skill)
        if skill in skills:
            ids[skill] = skills[skill]["id"]
            client.run("skill", "update", ids[skill], "--content", source["content"],
                       "--description", source["description"])
        else:
            ids[skill] = client.run("skill", "create", "--name", skill, "--content", source["content"],
                                    "--description", source["description"])["id"]
            done.append(f"创建技能 {skill}")
        remote = {f["path"]: f for f in client.run("skill", "get", ids[skill]).get("files") or []}
        for path, text in source["files"].items():
            if not same(remote.get(path) or {}, text):
                client.run("skill", "files", "upsert", ids[skill], "--path", path, "--content", text)
                done.append(f"{skill}/{path}")
        for path in sorted(set(remote) - set(source["files"])):
            client.run("skill", "files", "delete", ids[skill], remote[path]["id"], data=False)
            done.append(f"删除 {skill}/{path}")
        if source["skipped"]:
            done.append(f"{skill} 跳过非文本文件：{source['skipped']}")
    agents = {entry["name"]: entry for entry in client.run("agent", "list")}
    missing = [cfg["agents"][role] for role in ROLES if cfg["agents"][role] not in agents]
    if missing:
        raise ValueError(f"Multica 里没有这些 agent，请先在 Multica 创建（绑定本机 Codex runtime）：{missing}")
    for role, skill in ROLES.items():
        agent = agents[cfg["agents"][role]]
        client.run("agent", "skills", "set", agent["id"], "--skill-ids", ids[skill])
        client.run("agent", "update", agent["id"], "--instructions", instructions(cfg, role))
        done.append(f"{agent['name']} → {skill}")
    if prune:
        used = {s["name"] for a in client.run("agent", "list") for s in a.get("skills") or []}
        for name in LEGACY_SKILLS:
            if name in skills and name not in used:
                client.run("skill", "delete", skills[name]["id"], "--yes", data=False)
                done.append(f"删除旧技能 {name}")
    return done


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("operation", choices=("status", "sync"))
    parser.add_argument("--data-dir")
    parser.add_argument("--prune", action="store_true", help="Delete legacy workspace skills no agent uses.")
    args = parser.parse_args()
    try:
        cfg = settings(wb.data_root(argparse.Namespace(data_dir=args.data_dir)))
        client = connect(cfg)
        if args.operation == "status":
            result = inspect(cfg, client)
        else:
            result = {"synced": sync(cfg, client, args.prune), **inspect(cfg, client)}
        problems = [f"{role}: {entry['problem']}" for role, entry in result["agents"].items() if "problem" in entry]
        problems += [f"{skill} 与插件源码不一致" for skill, state in result["skills"].items() if state != "ok"]
        problems += [f"{role}: 技能应只有 {entry['skill']}" for role, entry in result["agents"].items()
                     if "assigned" in entry and entry["assigned"] != [entry["skill"]]]
        problems += [f"{role}: 指令需要同步" for role, entry in result["agents"].items()
                     if entry.get("instructions_current") is False]
        if not result["project"]:
            problems.append(f"没有项目「{cfg['project']}」：请在 Multica 创建，或修改配置 multica.project")
        wb.emit({"ok": not problems, "profile": cfg["profile"], **result, "problems": problems})
        return 0 if not problems else 1
    except (ValueError, OSError) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
