#!/usr/bin/env python3
"""Scene-based setup: check everything a scene needs, fix what can be fixed unattended.

Scenes: `investigate` (QA 提 Bug), `solution` (定时分析根因与方案), `execute` (定时修复与部署),
or `all`. Each item comes back with one status:

- `ok`: ready and verified (installed, logged in, resource reachable).
- `fix`: missing but `prepare.py fix` can do it unattended (fill config defaults, npm or
  Homebrew installs, `gh auth setup-git`).
- `user`: needs the person (a login, a token, a permission from an owner); `guide` lists
  the exact steps and `verify` says how it is checked afterwards.
- `host`: checked by the agent inside Codex (the chrome-devtools MCP and Chrome consent).
- `optional`: not needed for the scene to work, e.g. the scheduled job not installed yet.

`check` only reads and runs read-only probes. `fix` performs the `fix` items, then checks
again. Nothing here creates bugs, pushes, deploys or writes to Feishu.
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
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import workbench as wb  # noqa: E402

SCENES = {"investigate": "QA 提 Bug", "solution": "定时分析根因与方案", "execute": "定时修复与部署"}
NPM_PACKAGES = {"lark-cli": "@larksuite/cli", "codex": "@openai/codex", "mmdc": "@mermaid-js/mermaid-cli",
                "tutti-ops": "@tutti-os/tutti-ops-cli"}
SCHEDULE_PREFIX = {"solution": "com.tutti.bug-solution.", "execute": "com.tutti.bug-execute."}
SCRIPT = Path(__file__).resolve()


def run(command, timeout=60, **kwargs):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 127, str(error)
    return result.returncode, (result.stdout or "") + (result.stderr or "")


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
            elif (isinstance(target[key], list) and isinstance(default, list)
                  and all(isinstance(entry, dict) and "name" in entry for entry in default)):
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
                guide=["Node.js 用来安装 lark-cli、mmdc、tutti-ops，并运行 chrome-devtools MCP。",
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
    """QA 提 Bug creates a Room Task with `tutti-cli task create`, which only a Tutti Agent execution provides."""
    if shutil.which("tutti-cli"):
        return item("tutti-cli", "Tutti CLI（tutti-cli）", "ok", "可用")
    return item("tutti-cli", "Tutti CLI（tutti-cli）", "user", "当前环境没有 tutti-cli",
                guide=["QA 提 Bug 要在 Tutti Room 的 Agent 会话里运行：Task 用 `tutti-cli task create` 建在当前 Room，"
                       "这个命令只在 Tutti 的 Agent 执行环境中提供。",
                       "在要登记 Bug 的 Room 里打开 Agent，让它执行 `$tutti-bug-workflow:bug-investigate`；"
                       "确认 Computer 已更新到支持 `tutti-cli task create`／`edit`／`assign` 的版本。"],
                verify="在 Room Agent 会话中 `tutti-cli task --help` 列出 create、edit、assign")


def check_lark(cfg):
    missing = check_command("lark-cli", "飞书 CLI（lark-cli）", "读写 Bug 表")
    if missing:
        return [missing]
    items = []
    code, out = run(["lark-cli", "auth", "status"])
    try:
        status = json.loads(out[out.index("{"):]) if "{" in out else {}
    except ValueError:
        status = {}
    user = (status.get("identities") or {}).get("user") or {}
    if not status.get("appId"):
        return [item("lark-auth", "飞书应用与登录", "user", "lark-cli 还没有配置飞书应用",
                     guide=["Agent 在后台运行 `lark-cli config init --new`，把输出里的链接发给你；",
                            "你在浏览器里打开链接，按页面提示创建（或选择）飞书应用并确认；",
                            "完成后回复「已完成」，Agent 接着发起飞书登录。"],
                     verify="lark-cli auth status 返回 appId")]
    if user.get("tokenStatus") != "valid":
        return [item("lark-auth", "飞书登录", "user", user.get("message") or "飞书用户身份未登录或已过期",
                     guide=["Agent 运行 `lark-cli auth login --domain base,contact,drive --no-wait --json`，"
                            "用 `open <verification_url>` 在本机打开浏览器；",
                            "Agent 接着运行 `lark-cli auth login --device-code <device_code>` 等待授权完成；",
                            "你只需在弹出的浏览器里点「授权」，不用回复。"],
                     verify="lark-cli auth status 中 user.tokenStatus 为 valid")]
    items.append(item("lark-auth", "飞书登录", "ok", f"{user.get('userName')}（{user.get('openId')}）"))
    table = cfg.get("bug_report") or example()["bug_report"]
    code, out = run(["lark-cli", "base", "+field-list", "--as", "user", "--base-token", table["base_token"],
                     "--table-id", table["table_id"], "--format", "json"], timeout=90)
    try:
        data = json.loads(out[out.index("{"):]).get("data") or {}
    except ValueError:
        data = {}
    fields = next((value for value in data.values() if isinstance(value, list)), []) if isinstance(data, dict) else []
    present = {field.get("field_id") or field.get("id") for field in fields if isinstance(field, dict)}
    if code or not present:
        items.append(item("feishu-table", "Bug 管理表访问", "user", "读不到 Bug 管理表：" + out.strip()[-300:],
                          guide=[f"打开 Bug 管理表 {table.get('base_url')}，确认你能看到「{table.get('table_name')}」；",
                                 "看不到或不能编辑时，请表格负责人把你加为「可编辑」协作者；",
                                 "完成后回复「已完成」。"],
                          verify="lark-cli base +field-list 能读到表字段"))
        return items
    missing = sorted(key for key, value in (table.get("field_map") or {}).items() if value and value not in present)
    if missing:
        items.append(item("feishu-table", "Bug 管理表访问", "user", f"表里缺少字段：{missing}",
                          guide=["表结构和插件配置不一致：请维护人员在表里补上这些列，或更新 config.json 的 "
                                 "bug_report.field_map。"], verify="field_map 中每个字段 ID 都在表里"))
    else:
        items.append(item("feishu-table", "Bug 管理表访问", "ok", f"{len(present)} 个字段，配置的字段都在"))
    return items


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


def check_codex():
    missing = check_command("codex", "Codex CLI", "定时任务为每条 Bug 起会话")
    if missing:
        return [missing]
    code, out = run(["codex", "login", "status"])
    if code or "Logged in" not in out:
        return [item("codex-login", "Codex 登录", "user", out.strip()[-200:] or "未登录",
                     guide=["Agent 直接运行 `codex login`，它会在本机打开浏览器并等待；",
                            "你在浏览器里登录（ChatGPT 账号或 API key），不用回复。"],
                     verify="codex login status 显示 Logged in")]
    return [item("codex-login", "Codex 登录", "ok", out.strip().splitlines()[0])]


def check_mmdc():
    missing = check_command("mmdc", "Mermaid 渲染（mmdc）", "根因图转 PNG")
    if missing:
        return [missing]
    with tempfile.TemporaryDirectory() as folder:
        source, target = Path(folder) / "probe.mmd", Path(folder) / "probe.png"
        source.write_text("flowchart LR\n  A --> B\n", encoding="utf-8")
        code, out = run(["mmdc", "-i", str(source), "-o", str(target), "-b", "white"], timeout=120)
        rendered = target.is_file() and target.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    if not rendered:
        return [item("mmdc", "Mermaid 渲染（mmdc）", "user", "mmdc 渲染失败：" + out.strip()[-300:],
                     guide=["mmdc 依赖 puppeteer 自带的 Chromium：在终端运行 "
                            "`npx puppeteer browsers install chrome-headless-shell`，完成后回复「已完成」。"],
                     verify="mmdc 能把一张测试图渲染成 PNG")]
    return [item("mmdc", "Mermaid 渲染（mmdc）", "ok", "测试图渲染成功")]


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


def check_schedule(scene):
    folder = Path(os.environ.get("LAUNCH_AGENTS_DIR") or Path.home() / "Library/LaunchAgents")
    jobs = sorted(path.stem.split(".")[-1] for path in folder.glob(f"{SCHEDULE_PREFIX[scene]}*.plist"))
    name = "定时分析" if scene == "solution" else "定时修复"
    skill = "bug-solution" if scene == "solution" else "bug-execute"
    if jobs:
        return [item(f"{scene}-schedule", f"{name}任务", "ok", f"已开启：{jobs}")]
    if platform.system() != "Darwin":
        return [item(f"{scene}-schedule", f"{name}任务", "user", "定时任务依赖 macOS launchd，这台机器不是 macOS")]
    return [item(f"{scene}-schedule", f"{name}任务", "optional", "还没开启",
                 guide=[f"其他项都通过后，用 `$tutti-bug-workflow:{skill}` 开启：默认跟进人是当前飞书登录用户、"
                        "每小时一轮、处理全部优先级；可以指定跟进人和最低优先级（例如「只处理 P1 以上」）。"])]


def check(root, scenes, include_aws=False):
    items = [item("python", "Python 3.10+", "ok" if sys.version_info >= (3, 10) else "user",
                  platform.python_version()), check_config(root)]
    cfg = wb.read_json(root / "config.json") if (root / "config.json").is_file() else example()
    items.append(check_node())
    if {"solution", "execute"} & scenes:
        items += check_lark(cfg)
        items += check_repositories(cfg)
        items += check_codex()
    if "solution" in scenes:
        items += check_mmdc()
    if "execute" in scenes:
        items += check_github(cfg)
    if {"investigate", "execute"} & scenes:
        items += check_chrome()
    if "investigate" in scenes:
        items.append(check_tutti_cli())
        items += check_tutti_ops(root, cfg)
        items += check_computer_logs(cfg)
    if include_aws:
        code, out = run([sys.executable, str(SCRIPT.parent / "workbench.py"), "setup-aws-cli", "--check-auth",
                         "--data-dir", str(root)], timeout=120)
        items.append(item("aws", "AWS CLI 与登录", "ok" if code == 0 and '"authenticated"' in out else "user",
                          out.strip()[-300:], guide=["按 references/aws-cli.md 完成 AWS SSO 登录后回复「已完成」。"]))
    for scene in ("solution", "execute"):
        if scene in scenes:
            items += check_schedule(scene)
    return items


# ---------------------------------------------------------------- fixes

def apply_fix(root, fix):
    if fix == "config":
        return fix_config(root)
    if fix.startswith("npm:"):
        name = fix[4:]
        if name == "tutti-ops":
            return f"tutti-ops：{wb.ensure_tutti_ops(root, install=True)['action']}"
        code, out = run(["npm", "install", "-g", NPM_PACKAGES[name]], timeout=600)
        if code:
            raise ValueError(f"npm install -g {NPM_PACKAGES[name]} 失败：{out.strip()[-400:]}")
        return f"已安装 {NPM_PACKAGES[name]}"
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
    parser.add_argument("--include", action="append", choices=("aws",), default=[])
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    try:
        root = wb.data_root(argparse.Namespace(data_dir=args.data_dir))
        scenes = set(SCENES) if "all" in args.scene else set(args.scene)
        items = check(root, scenes, "aws" in args.include)
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
        wb.emit(report(scenes, check(root, scenes, "aws" in args.include), done, errors))
        return 0 if not errors else 1
    except (ValueError, OSError) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
