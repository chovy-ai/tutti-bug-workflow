---
name: bug-setup
description: 准备 tutti-bug-workflow 的运行环境：先让用户选场景（QA 提 Bug／修复与部署／全部），自动检查、安装能装的工具并补齐默认配置，需要本人操作的登录和授权一步步引导、完成后复查；也支持只列出准备情况。两个场景都只对接 Tutti 任务系统。
---

# 准备工作台

QA 提 Bug（`$tutti-bug-workflow:bug-investigate`）、验收打回（`$tutti-bug-workflow:bug-reopen`）和修复与部署（`$tutti-bug-workflow:bug-execute`）共用的准备入口：**选场景 → 检查 → 能做的直接做 → 一步步引导本人操作 → 复查收尾**。目标是用户只需要做必须本人做的事（登录、授权、找管理员要权限），其余 Agent 全部完成。

脚本路径相对本 Skill 目录（`skills/bug-setup/`），都输出一段 JSON。配置和运行数据在数据目录（默认 `~/.local/share/bug-workbench`），插件更新不影响。

## 1. 选场景

用户已经说清楚（「准备 QA 提 Bug 的环境」「准备修 Bug 的环境」）就直接用；否则**先问这一个问题**，其他都不用问：

> 要准备哪个场景？
> 1. **QA 提 Bug**：自动采集页面和 Computer 现场日志，用全局 tutti-cli 以你的 Tutti 账号在指定 Room 建 Task；验收不通过时带现场打回也用这一套
> 2. **修复与部署**（RD）：指定一条 Bug Task 修复，提 PR、部署 PPE、自验证，结果回复到 Task
> 3. **全部**

用户说「我是 QA」按 1；「我是 RD」按 2；拿不准建议「全部」。场景对应 `--scene investigate`／`execute`／`all`，可重复。

两个场景都只对接 Tutti 任务系统（用 tutti-cli 读写 Room 里的 Task），不用飞书表，也没有定时任务。

## 2. 检查

```sh
python3 scripts/prepare.py check --scene investigate --scene execute   # 按选的场景
```

逐项返回状态：

| 状态 | 含义 | 谁来做 |
|---|---|---|
| `ok` | 已就绪并实际验证过（装好、登录有效、资源能访问） | — |
| `fix` | 缺，但能无人值守补上 | Agent，第 3 步 |
| `user` | 需要本人操作（登录、Token、找负责人要权限），带 `guide` 步骤和 `verify` 复查方法 | 用户，Agent 引导，第 4 步 |
| `host` | 需要 Agent 在 Codex 里实际验证（chrome-devtools MCP 与 Chrome 授权） | Agent＋用户点允许 |
| `optional` | 场景能用，但还可以更好 | 收尾时询问 |

先给用户一张简短的表：哪些已就绪、哪些我马上自动处理、哪些需要你。用户只要求「列一下要准备什么」时到这里结束，不安装、不登录。

## 3. 能做的直接做

有 `fix` 项就直接运行，不用征求同意：

```sh
python3 scripts/prepare.py fix --scene investigate --scene execute
```

它会：用默认配置补齐数据目录的 `config.json`（只补缺的项，已有值不动，原文件备份为 `config.before-prepare.json`）；用 npm 安装缺少的 tutti-ops；tutti-cli（需 Node.js 24+）每次都和 npm 上的最新版比对，没装或不是最新就运行 `npm install -g @tutti-os/tutti-cli@latest`。tutti-cli 的安装、登录与 PATH 冲突处理见 [Tutti CLI](references/tutti-cli.md)。然后自动复查。

`fix_errors` 里的失败先自己处理：npm 全局目录没有写权限时改用 nvm 的 Node；网络失败重试一次；仍然不行就转成 `user` 项，写清原因和用户要做的事。

`user` 项里 Agent 能先做的部分也直接做，用户只做最后那一下：

| 项 | Agent 先做 | 用户做 |
|---|---|---|
| Tutti CLI 未登录 | 后台运行 `tutti-cli login`（会自己打开 Tutti 登录页并等待，最长 5 分钟），返回后 `tutti-cli whoami --json` 确认 | 在浏览器里用自己的 Tutti 账号登录，不用回复 |
| GitHub 登录（修复与部署） | 给出 `gh auth login -h github.com -s repo,workflow` | 在终端运行，按提示在浏览器授权，回复「已完成」 |
| Tutti CLI 需要 Node.js 24+ | 给出 `nvm install 24 && nvm use 24 && nvm alias default 24`，完成后再 `fix` 自动安装 `@tutti-os/tutti-cli` | 在终端运行这一行，回复「已完成」 |
| Chrome 连接（`host`） | 调用 chrome-devtools 的 `list_pages` 和 `list_webmcp_tools` | Chrome 弹窗点「允许」；没开远程调试或 WebMCP flag 时按 `guide` 打开 |
| tutti-ops Token | 准备好 `configure-tutti-token` 命令 | 在管理端创建 Token，在终端隐藏粘贴 |

## 4. 一步步引导本人操作

按顺序**一次只引导一项**：Tutti CLI → GitHub → tutti-ops → Chrome → 需要管理员的权限（只引导所选场景用得到的）。每项都这样说：

1. **为什么**：一句话说用途（「为了用你的账号在 Room 里建 Task」「为了推送修复分支、触发 PPE 部署」）。
2. **你要做什么**：照 `guide` 写成编号步骤；要在终端运行的命令给出完整、可直接复制的一行；网页给出真实链接。
3. **做完回复「已完成」**，我来检查。

能由 Agent 发起、只需用户在浏览器里点一下的登录（上表），不要让用户回复，命令返回后直接复查。收到「已完成」后重新 `check`，以实际结果为准；通过就进入下一项，没通过就说明这次具体卡在哪、下一步怎么做。

- Token、密码、App Secret 只在用户本机的隐藏输入里出现，不要让用户发到对话里，也不写进配置或 Task。
- 需要管理员处理的（管理端账号、Room 成员身份、GitHub 仓库写权限与部署权限）：告诉用户找谁、要什么权限，然后继续其他项，不卡住整个流程。
- 不用试建 Task、推送、部署来测试权限；不自己给自己加权限。

## 5. 收尾

再跑一次 `check`，用一张表交付：每个场景「已就绪／等你操作／等管理员」，以及受影响的能力。

- **修复与部署**：告诉用户怎么用：在本机 Codex 里说「修复这个 Task <链接>」，并贴上认可的方案（通常是 Room Agent 在 Task 里回复的根因分析）；修复结果会回复到这个 Task。
- **QA 提 Bug**：告诉用户怎么用：在本机 Codex 里说「记个 bug：<现象>」，带上房间名（或房主名字、Room ID）和截图即可，会先在你的本地房间里找；Task 用 `tutti-cli login` 登录的账号建在该 Room，创建后在任务看板指派跟进人。修过的 Bug 还有问题时，发 Task 链接和截图说「这里还有问题，打回去」，会采集这一轮的现场、评论到原 Task、改回待办，并交给 Room Agent 重新分析。

## 默认配置

以下都有默认值，用户不需要提供；要改就告诉 Agent 或编辑数据目录的 `config.json`，详见 [配置说明](references/configuration.md)。

| 配置 | 默认值 |
|---|---|
| 数据目录 | `~/.local/share/bug-workbench`（可用 `BUG_WORKBENCH_DATA` 改） |
| 代码仓库（修复与部署） | tutti、tutti-server、tsh-websocket 的 main，缓存在数据目录 `repositories/` |
| 修复分支与泳道 | 分支 `codex/bug-<Task ID 前 8 位>`，泳道 `ppe-bug-<同样 8 位>` |
| PPE 部署 | tutti-server／tsh-websocket `deploy-lane.yml`，前端 `platform-web-preview.yml`，Computer `computer-artifacts-release.yml`；连接器授权默认关闭 |
| tutti-ops 管理端 | `https://admin.tutti.sh` |
| 本机 Computer 日志 | `~/.tutti-amp/computer/logs/` 下的 companion、desktopd、runtime-host 日志，以及 `${TMPDIR}/tutti-codex-appserver-startup.jsonl` |

## 可选与参考

- 单项工具命令仍可直接用：`scripts/workbench.py doctor`、`setup-tutti-ops --install`、`configure-tutti-token --admin-url https://admin.tutti.sh`、`configure-mcp`。
- 引导话术与各入口的授权细节：[易懂的准备与授权流程](references/setup-user-guide.md)。
- 各能力的背景：[Web 日志](references/web-logs.md)、[tutti-ops 获取日志](references/tutti-ops-computer-logs.md)、[Computer 日志](references/computer-logs.md)、[提 Bug 后的会话上传](references/session-upload.md)、[工具目录](references/tool-setup.md)、[代码缓存](references/repository-cache.md)、[工作流与交接](references/workflow.md)。
