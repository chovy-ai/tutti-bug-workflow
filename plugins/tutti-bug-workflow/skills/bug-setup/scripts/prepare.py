#!/usr/bin/env python3
"""Scene-based setup: check everything a scene needs, fix what can be fixed unattended.

Scenes: `investigate` (QA 提 Bug) and `execute` (修复一条 Bug Task 并部署 PPE), or `all`.
Both work only with the Tutti task system through tutti-cli. Each item comes back with one status:

- `ok`: ready and verified (installed, logged in, resource reachable).
- `fix`: missing but `prepare.py fix` can do it unattended (fill config defaults, npm or
  Homebrew installs, `gh auth setup-git`).
- `user`: needs the person (a login, a token, a permission from an owner); `guide` lists
  the exact steps and `verify` says how it is checked afterwards.
- `host`: checked by the agent inside Codex (the chrome-devtools MCP and Chrome consent).
- `optional`: not needed for the scene to work, e.g. no local Computer logs on this machine.

`check` only reads and runs read-only probes. `fix` performs the `fix` items, then checks
again. Nothing here creates Tasks, pushes or deploys.
"""

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workbench as wb  # noqa: E402

SCENES = {"investigate": "QA 提 Bug", "execute": "修复与部署"}
NPM_PACKAGES = {"tutti-ops": "@tutti-os/tutti-ops-cli", "tutti-cli": "@tutti-os/tutti-cli"}
SCRIPT = Path(__file__).resolve()


def run(command, timeout=60, stdout_only=False, **kwargs):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return result.returncode, ((result.stdout or "") if stdout_only and result.returncode == 0
                               else (result.stdout or "") + (result.stderr or ""))


def item(identifier, label, status, detail="", guide=None, verify=None, fix=None):
    entry = {"id": identifier, "label": label, "status": status, "detail": detail}
    if guide:
        entry["guide"] = guide
    if verify:
        entry["verify"] = verify
    if fix:
        entry["fix"] = fix
    return entry


# ---------------------------------------------------------------- configuration

def merge_defaults(value, defaults):
    """Add what the defaults have and the config lacks; never change a value already set."""
    added = []

    def merge(target, source, path):
        for key, default in source.items():
            if key not in target or target[key] is None and default is not None:
                target[key] = default
                added.append(f"{path}{key}")
            elif isinstance(target[key], dict) and isinstance(default, dict):
                merge(target[key], default, f"{path}{key}.")
            elif (isinstance(target[key], list) and isinstance(default, list) and default
                  and all(isinstance(entry, dict) and "name" in entry for entry in default)):
                for index, entry in enumerate(target[key]):
                    if not isinstance(entry, dict):
                        raise ValueError(f"配置 {path}{key}[{index}] 必须是对象，当前为 {type(entry).__name__}")
                names = {entry.get("name") for entry in target[key] if isinstance(entry, dict)}
                for entry in default:
                    if entry["name"] not in names:
                        target[key].append(entry)
                        added.append(f"{path}{key}[{entry['name']}]")
                for entry in target[key]:
                    match = next((d for d in default if d["name"] == entry.get("name")), None)
                    if isinstance(entry, dict) and match:
                        merge(entry, match, f"{path}{key}[{entry['name']}].")
            elif isinstance(target[key], list) and not target[key] and default:
                target[key] = default  # e.g. empty computer-local paths get the standard ones
                added.append(f"{path}{key}")

    merge(value, defaults, "")
    return added


def example():
    return wb.read_json(wb.PLUGIN_ROOT / "config/workbench.example.json")


def check_config(root):
    target = root / "config.json"
    if not target.is_file():
        return item("config", "工作台配置", "fix", f"{target} 还不存在，将用默认配置创建", fix="config")
    current = wb.read_json(target)
    missing = merge_defaults(json.loads(json.dumps(current)), example())
    if missing:
        return item("config", "工作台配置", "fix", f"缺少 {len(missing)} 项默认配置：{', '.join(missing[:8])}"
                    + ("…" if len(missing) > 8 else ""), fix="config")
    return item("config", "工作台配置", "ok", str(target))


def fix_config(root):
    target = root / "config.json"
    (root / "tools").mkdir(parents=True, exist_ok=True)
    current = wb.read_json(target) if target.is_file() else {}
    if target.is_file():
        shutil.copyfile(target, target.with_name("config.before-prepare.json"))
    added = merge_defaults(current, example())
    wb.write_json(target, current)
    return f"配置 {target}：补上 {len(added)} 项默认值"


# ---------------------------------------------------------------- probes

def node_ok():
    code, out = run(["node", "--version"])
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    return code == 0 and match and int(match[1]) >= 20 and shutil.which("npm"), out.strip()


def check_node():
    ready, version = node_ok()
    if ready:
        return item("node", "Node.js 20+ 与 npm", "ok", version)
    return item("node", "Node.js 20+ 与 npm", "user", f"当前：{version or '未安装'}",
                guide=["Node.js 用来安装 tutti-cli、tutti-ops，并运行 chrome-devtools MCP。",
                       "macOS 推荐：在终端运行 `brew install node`（没有 Homebrew 先看 https://brew.sh）；"
                       "或用 nvm：`nvm install 22 && nvm use 22`。",
                       "装好后重新打开终端，回复「已完成」。"],
                verify="node --version 为 v20 及以上，npm 可用")


def check_command(name, label, scene_hint):
    if shutil.which(name):
        return None
    package = NPM_PACKAGES.get(name)
    if package and node_ok()[0]:
        return item(name, label, "fix", f"未安装，将运行 npm install -g {package}", fix=f"npm:{name}")
    if name == "gh" and shutil.which("brew"):
        return item(name, label, "fix", "未安装，将运行 brew install gh", fix="brew:gh")
    steps = {"git": ["在终端运行 `xcode-select --install`（或 `brew install git`），装好后回复「已完成」。"],
             "gh": ["安装 GitHub CLI：https://cli.github.com （macOS 可 `brew install gh`），装好后回复「已完成」。"]}
    return item(name, label, "user", f"未安装（{scene_hint}）",
                guide=steps.get(name) or [f"先装好 Node.js 20+，再由 Agent 运行 `npm install -g {package}`。"],
                verify=f"`{name}` 在 PATH 中可执行")


def check_tutti_cli():
    """Both scenes talk to Room Tasks through the global account CLI (@tutti-os/tutti-cli, Node 24+)."""
    label = "Tutti CLI（tutti-cli，账号登录版）"
    code, out = run(["tutti-cli", "--help"]) if shutil.which("tutti-cli") else (127, "")
    detail = None
    # The usage block of `task comment` runs until the next command line.
    comment = re.search(r"tutti-cli task comment\b(.*?)(?=\n\s*tutti-cli |\n\s*\n|\Z)", out, re.S)
    if code or any(f"tutti-cli {command}" not in out for command in ("login", "room list", "task run")):
        detail = ("未安装" if not shutil.which("tutti-cli") else
                  "PATH 里的 tutti-cli 不是账号登录版（没有 login 命令）" if "tutti-cli login" not in out else
                  "版本过旧，没有 room list／task run（按房间名查房间、交给 Room Agent 分析根因）")
    elif not comment or "--file" not in comment[1]:
        detail = "版本过旧，task comment 不支持 --file（修复回复要把验证截图作为评论附件）"
    elif "tutti-cli task status" not in out:
        detail = "版本过旧，没有 task status（验收打回要把 Task 改回待办）"
    elif shutil.which("npm"):
        # Always run the latest release; when npm cannot be reached keep the installed one.
        latest_code, latest = run(["npm", "view", "@tutti-os/tutti-cli", "version"], stdout_only=True)
        current_code, current = run(["tutti-cli", "--version"], stdout_only=True)
        version_pattern = r"v?(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)"
        latest_version = re.fullmatch(version_pattern, latest.strip()) if latest_code == 0 else None
        current_version = re.fullmatch(version_pattern, current.strip()) if current_code == 0 else None
        if latest_version and (not current_version or current_version[1] != latest_version[1]):
            detail = f"当前 {current.strip() or '未知版本'}，npm 最新 {latest_version[1]}"
    if detail:
        version = run(["node", "--version"])[1].strip()
        major = re.match(r"v(\d+)\.", version)
        if major and int(major[1]) >= 24 and shutil.which("npm"):
            return item("tutti-cli", label, "fix", f"{detail}，将运行 npm install -g @tutti-os/tutti-cli@latest",
                        fix="npm:tutti-cli")
        return item("tutti-cli", label, "user", f"{detail}；需要 Node.js 24+（当前：{version or '未安装'}）",
                    guide=["提 Bug、验收打回、修复回复都用全局安装的 tutti-cli 以你的 Tutti 账号读写 Room 里的 Task，它要求 Node.js 24 及以上。",
                           "用 nvm：`nvm install 24 && nvm use 24`（或 `brew install node`），然后回复「已完成」，"
                           "Agent 会运行 `npm install -g @tutti-os/tutti-cli@latest`。"],
                    verify="`tutti-cli --help` 列出 login、room list、task create、task run、task status，task comment 带 --file")
    code, out = run(["tutti-cli", "whoami", "--json"])
    if code == 0:
        try:
            user = json.loads(out[out.index("{"):])
        except ValueError:
            user = {}
        if isinstance(user, dict) and type(user.get('userId')) in (str, int) and str(user['userId']).strip():
            return item("tutti-cli", label, "ok", f"已登录：{user.get('name') or user['userId']}")
        out = "whoami 未返回有效的账号 userId，请重新登录后复查"
    return item("tutti-cli", label, "user", f"未登录或登录已过期：{out.strip()[-200:]}",
                guide=["在终端运行 `tutti-cli login`，浏览器会打开 Tutti 登录页，用你自己的 Tutti 账号完成登录（需是目标 Room 的成员）。",
                       "登录完成后回复「已完成」。"],
                verify="`tutti-cli whoami --json` 返回账号")


def check_repositories(cfg):
    missing = check_command("git", "Git", "拉取代码")
    if missing:
        return [missing]
    failed = []
    for repo in cfg.get("repositories") or example()["repositories"]:
        code, out = run(["git", "ls-remote", "--heads", repo["url"], repo.get("base_branch") or "main"], timeout=90,
                        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if code or not out.strip():
            failed.append(repo["name"])
    if failed:
        return [item("repositories", "代码仓库读取", "user", f"读不到：{failed}",
                     guide=["先完成 GitHub 登录：在终端运行 `gh auth login -h github.com -s repo,workflow`，"
                            "按提示在浏览器授权；Agent 随后运行 `gh auth setup-git` 让 git 复用这个登录；",
                            "仍然读不到时，请 tutti-lab 组织管理员把你的 GitHub 账号加进对应仓库；",
                            "完成后回复「已完成」。"],
                     verify="git ls-remote 能读到 tutti、tutti-server、tsh-websocket 的 main")]
    return [item("repositories", "代码仓库读取", "ok", "tutti、tutti-server、tsh-websocket 都能读取")]


def check_github(cfg):
    missing = check_command("gh", "GitHub CLI（gh）", "推送、提 PR、触发部署")
    if missing:
        return [missing]
    code, out = run(["gh", "auth", "status"])
    scopes = set(re.findall(r"'([a-z:_]+)'", out))
    login = ["在终端运行 `gh auth login -h github.com -s repo,workflow`，按提示在浏览器授权；",
             "完成后回复「已完成」。"]
    if code:
        return [item("gh-auth", "GitHub 登录", "user", "gh 未登录", guide=login,
                     verify="gh auth status 已登录且包含 repo、workflow 权限")]
    if not {"repo", "workflow"} <= scopes:
        return [item("gh-auth", "GitHub 登录", "user", f"缺少权限范围：{sorted({'repo', 'workflow'} - scopes)}",
                     guide=["在终端运行 `gh auth refresh -h github.com -s repo,workflow`，按提示在浏览器确认；",
                            "完成后回复「已完成」。"], verify="gh auth status 包含 repo、workflow")]
    items = [item("gh-auth", "GitHub 登录", "ok", out.split("account", 1)[-1].split("(")[0].strip())]
    if run(["git", "config", "--global", "--get-regexp", r"credential\..*github\.com.*helper"])[0]:
        items.append(item("gh-git", "git 复用 gh 登录", "fix", "将运行 gh auth setup-git", fix="gh-setup-git"))
    no_push = []
    repositories = {section["repository"] for section in (cfg.get("deploy") or example()["deploy"]).values()
                    if isinstance(section, dict) and section.get("repository")}
    for repository in sorted(repositories):
        code, out = run(["gh", "api", f"repos/{repository}", "--jq", ".permissions.push"])
        if code or out.strip() != "true":
            no_push.append(repository)
    if no_push:
        items.append(item("deploy-permission", "推送与触发部署权限", "user", f"没有写权限：{no_push}",
                          guide=["推送修复分支、提 PR、触发 PPE 部署工作流都需要仓库写权限；",
                                 "请 tutti-lab 组织管理员给你的 GitHub 账号这些仓库的 Write 权限，完成后回复「已完成」。"],
                          verify="gh api repos/<仓库> 的 permissions.push 为 true"))
    else:
        items.append(item("deploy-permission", "推送与触发部署权限", "ok", "、".join(sorted(repositories))))
    return items


def check_tutti_ops(root, cfg):
    missing = check_command("tutti-ops", "tutti-ops CLI", "上传会话、召回 Computer 日志、查 Server 日志")
    if missing:
        return [missing]
    admin = (cfg.get("tutti_ops") or example()["tutti_ops"])["admin_url"]
    code, out = run(["tutti-ops", "--admin-url", admin, "--mode", "read", "auth", "status", "--metadata-only", "true"])
    try:
        ok = json.loads(out[out.index("{"):]).get("ok") is True
    except ValueError:
        ok = False
    if code or not ok:
        return [item("tutti-ops-auth", "tutti-ops 管理端 Token", "user", "Token 缺失或失效",
                     guide=[f"打开 {admin}/admin-tokens（左侧「全局 → 管理密钥」），登录管理端账号；",
                            "点「新增密钥」，备注填 `tutti-bug-workflow`；点「详细控制模块权限」，"
                            "整体权限和「Computer 与任务」都选「可写」（只查历史日志可选只读）；",
                            "点「创建」，立即复制完整 Token（只显示一次）；",
                            f"在终端运行 `python3 {SCRIPT.parent / 'workbench.py'} configure-tutti-token --admin-url {admin}`，"
                            "在 `Tutti admin token (hidden):` 处粘贴（不会显示），回车；",
                            "回复「已完成」。没有管理端权限时请环境维护人员代为创建。"],
                     verify="tutti-ops auth status 返回 ok")]
    return [item("tutti-ops-auth", "tutti-ops 管理端 Token", "ok", admin)]


def check_chrome():
    ready, _ = node_ok()
    if not ready or not shutil.which("npx"):
        return [item("chrome-devtools", "本机 Chrome 连接（chrome-devtools MCP）", "user", "需要先装好 Node.js 20+ 与 npx")]
    return [item("chrome-devtools", "本机 Chrome 连接（chrome-devtools MCP）", "host",
                 "插件已注册 chrome-devtools MCP；需要 Agent 在 Codex 里实际连一次",
                 guide=["在 Chrome 打开 `chrome://inspect/#remote-debugging`，勾选允许远程调试；",
                        "提 Bug 读页面日志还需：打开 `chrome://flags/#enable-webmcp-testing` 设为 Enabled，重启 Chrome；",
                        "在 Chrome 里登录 https://tutti.sh；",
                        "Agent 调用 chrome-devtools 的 `list_pages` 时，Chrome 会弹窗询问，点「允许」。"],
                 verify="Agent 在 Codex 里调用 chrome-devtools list_pages 成功（提 Bug 场景再看到 get_web_logs 工具）")]


def check_computer_logs(cfg):
    source = next((s for s in cfg.get("log_sources") or example()["log_sources"] if s.get("name") == "computer-local"), {})
    found = []
    for raw in source.get("paths") or []:
        try:
            if wb.resolve_log_path(raw).is_file():
                found.append(raw)
        except (ValueError, RuntimeError):
            continue
    if found:
        return [item("computer-logs", "本机 Computer 日志", "ok", f"找到 {len(found)} 个日志文件")]
    return [item("computer-logs", "本机 Computer 日志", "optional",
                 "本机没有 Computer 日志（这台机器没跑过 Tutti Computer 时正常）；远端设备的日志用 tutti-ops 召回")]


def check(root, scenes):
    items = [item("python", "Python 3.10+", "ok" if sys.version_info >= (3, 10) else "user",
                  platform.python_version()), check_config(root)]
    cfg = wb.read_json(root / "config.json") if (root / "config.json").is_file() else example()
    items.append(check_node())
    items.append(check_tutti_cli())
    if "execute" in scenes:
        items += check_repositories(cfg)
        items += check_github(cfg)
    items += check_chrome()
    if "investigate" in scenes:
        items += check_tutti_ops(root, cfg)
        items += check_computer_logs(cfg)
    return items


# ---------------------------------------------------------------- fixes

def apply_fix(root, fix):
    if fix == "config":
        return fix_config(root)
    if fix.startswith("npm:"):
        name = fix[4:]
        if name == "tutti-ops":
            return f"tutti-ops：{wb.ensure_tutti_ops(root, install=True)['action']}"
        package = NPM_PACKAGES[name] + ("@latest" if name == "tutti-cli" else "")
        code, out = run(["npm", "install", "-g", package], timeout=600)
        if code:
            raise ValueError(f"npm install -g {package} 失败：{out.strip()[-400:]}")
        return f"已安装 {package}"
    if fix == "brew:gh":
        code, out = run(["brew", "install", "gh"], timeout=900)
        if code:
            raise ValueError(f"brew install gh 失败：{out.strip()[-400:]}")
        return "已安装 gh"
    if fix == "gh-setup-git":
        code, out = run(["gh", "auth", "setup-git"])
        if code:
            raise ValueError(f"gh auth setup-git 失败：{out.strip()[-300:]}")
        return "git 已复用 gh 的 GitHub 登录"
    raise ValueError(f"Unknown fix {fix!r}")


def report(scenes, items, done=None, errors=None):
    counts = {status: sum(1 for entry in items if entry["status"] == status)
              for status in ("ok", "fix", "user", "host", "optional")}
    result = {"scenes": {scene: SCENES[scene] for scene in sorted(scenes)}, "summary": counts, "items": items}
    if done is not None:
        result["fixed"] = done
        result["fix_errors"] = errors
    result["ready"] = counts["fix"] == 0 and counts["user"] == 0
    result["next"] = ("运行 prepare.py fix 自动处理 fix 项" if counts["fix"] else
                      "按 guide 逐项引导用户完成 user 项，完成后再 check" if counts["user"] else
                      "在 Codex 里验证 host 项" if counts["host"] else "全部就绪")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "fix"))
    parser.add_argument("--scene", action="append", choices=(*SCENES, "all"), required=True)
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    try:
        root = wb.data_root(argparse.Namespace(data_dir=args.data_dir))
        scenes = set(SCENES) if "all" in args.scene else set(args.scene)
        items = check(root, scenes)
        if args.operation == "check":
            wb.emit(report(scenes, items))
            return 0
        done, errors = [], []
        for entry in items:
            if entry["status"] == "fix":
                try:
                    done.append(apply_fix(root, entry["fix"]))
                except (ValueError, OSError) as error:
                    errors.append({"id": entry["id"], "error": str(error)})
        wb.emit(report(scenes, check(root, scenes), done, errors))
        return 0 if not errors else 1
    except (ValueError, OSError) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
