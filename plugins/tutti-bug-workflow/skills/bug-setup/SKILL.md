---
name: bug-setup
description: 准备 tutti-bug-workflow 的运行环境：先让用户选场景（QA 提 Bug／定时分析／定时修复／全部），自动检查、安装能装的工具并补齐默认配置，需要本人操作的登录和授权一步步引导、完成后复查，最后可直接开启定时任务；也支持只列出准备情况。
---

# 准备工作台

三个业务 Skill 共用的准备入口：**选场景 → 检查 → 能做的直接做 → 一步步引导本人操作 → 复查收尾**。目标是用户只需要做必须本人做的事（登录、授权、找管理员要权限），其余 Agent 全部完成。

脚本路径相对本 Skill 目录（`skills/bug-setup/`），都输出一段 JSON。配置和运行数据在数据目录（默认 `~/.local/share/bug-workbench`），插件更新不影响。

## 1. 选场景

用户已经说清楚（「准备 QA 提 Bug 的环境」「我要开定时修复」）就直接用；否则**先问这一个问题**，其他都不用问：

> 要准备哪个场景？
> 1. **QA 提 Bug**：自动采集页面／Server／Computer 现场日志，用全局 tutti-cli 以你的 Tutti 账号在指定 Room 建 Task
> 2. **定时分析**（RD）：每小时分析分给你的 Bug，写根因、修复方式、验收标准和根因图
> 3. **定时修复**（RD）：每小时修复已批准的 Bug，提 PR、部署 PPE、自验证并回填
> 4. **全部**
>
> 可以多选，比如「2 和 3」。

用户说「我是 QA」按 1；「我是 RD」按 2＋3；拿不准建议「全部」。场景对应 `--scene investigate`／`solution`／`execute`／`all`，可重复。

## 2. 检查

```sh
python3 scripts/prepare.py check --scene solution --scene execute
```

逐项返回状态：

| 状态 | 含义 | 谁来做 |
|---|---|---|
| `ok` | 已就绪并实际验证过（装好、登录有效、资源能访问） | — |
| `fix` | 缺，但能无人值守补上 | Agent，第 3 步 |
| `user` | 需要本人操作（登录、Token、找负责人要权限），带 `guide` 步骤和 `verify` 复查方法 | 用户，Agent 引导，第 4 步 |
| `host` | 需要 Agent 在 Codex 里实际验证（chrome-devtools MCP 与 Chrome 授权） | Agent＋用户点允许 |
| `optional` | 场景能用，但还可以更好（如定时任务还没开） | 收尾时询问 |

先给用户一张简短的表：哪些已就绪、哪些我马上自动处理、哪些需要你。用户只要求「列一下要准备什么」时到这里结束，不安装、不登录。

## 3. 能做的直接做

有 `fix` 项就直接运行，不用征求同意：

```sh
python3 scripts/prepare.py fix --scene solution --scene execute
```

它会：用默认配置补齐数据目录的 `config.json`（只补缺的项，已有值不动，原文件备份为 `config.before-prepare.json`）；用 npm 安装缺少的 lark-cli、codex、mmdc、tutti-ops、tutti-cli（需 Node.js 24+）；用 Homebrew 安装 gh。tutti-cli 的安装、登录与 PATH 冲突处理见 [Tutti CLI](references/tutti-cli.md)；运行 `gh auth setup-git` 让 git 复用 GitHub 登录。然后自动复查。

`fix_errors` 里的失败先自己处理：npm 全局目录没有写权限时改用 nvm 的 Node；网络失败重试一次；仍然不行就转成 `user` 项，写清原因和用户要做的事。

`user` 项里 Agent 能先做的部分也直接做，用户只做最后那一下：

| 项 | Agent 先做 | 用户做 |
|---|---|---|
| 飞书应用未配置 | 后台运行 `lark-cli config init --new`，取出链接 | 打开链接，按页面创建应用 |
| 飞书登录 | `lark-cli auth login --domain base,contact,drive --no-wait --json` → `open <verification_url>` 在本机打开浏览器 → `lark-cli auth login --device-code <code>` 等待完成 | 在弹出的浏览器里点「授权」，不用回复 |
| Codex 登录 | 直接运行 `codex login`（会自己打开浏览器并等待） | 在浏览器里登录，不用回复 |
| AWS SSO 过期 | 直接运行 `aws sso login`（会自己打开浏览器并等待） | 在浏览器里点「允许」，不用回复 |
| Tutti CLI 未登录 | 后台运行 `tutti-cli login`（会自己打开 Tutti 登录页并等待，最长 5 分钟），返回后 `tutti-cli whoami --json` 确认 | 在浏览器里用要建 Bug 的账号登录，不用回复 |
| Tutti CLI 需要 Node.js 24+ | 给出 `nvm install 24 && nvm use 24 && nvm alias default 24`，完成后再 `fix` 自动安装 `@tutti-os/tutti-cli` | 在终端运行这一行，回复「已完成」 |
| Chrome 连接（`host`） | 调用 chrome-devtools 的 `list_pages`（提 Bug 场景再 `list_webmcp_tools`） | Chrome 弹窗点「允许」；没开远程调试或 WebMCP flag 时按 `guide` 打开 |
| tutti-ops Token | 准备好 `configure-tutti-token` 命令 | 在管理端创建 Token，在终端隐藏粘贴 |

## 4. 一步步引导本人操作

按顺序**一次只引导一项**：飞书 → GitHub → Codex → Tutti CLI → tutti-ops → Chrome → 需要管理员的权限。每项都这样说：

1. **为什么**：一句话说用途（「为了读取和回填 Bug 表」）。
2. **你要做什么**：照 `guide` 写成编号步骤；要在终端运行的命令给出完整、可直接复制的一行；网页给出真实链接。
3. **做完回复「已完成」**，我来检查。

能由 Agent 发起、只需用户在浏览器里点一下的登录（上表），不要让用户回复，命令返回后直接复查。收到「已完成」后重新 `check`，以实际结果为准；通过就进入下一项，没通过就说明这次具体卡在哪、下一步怎么做。

- Token、密码、App Secret 只在用户本机的隐藏输入里出现，不要让用户发到对话里，也不写进配置或 Bug 表。
- 需要管理员处理的（表格编辑权限、GitHub 仓库写权限、管理端账号）：告诉用户找谁、要什么权限，然后继续其他项，不卡住整个流程。
- 不用试建 Bug、推送、部署来测试权限；不自己给自己加权限。

## 5. 收尾

再跑一次 `check`，用一张表交付：每个场景「已就绪／等你操作／等管理员」，以及受影响的能力。

- **定时分析／定时修复**：全部就绪后询问「要现在开启吗？默认跟进人是你（当前飞书登录用户），每小时一轮，处理全部优先级；可以指定跟进人或只处理某个优先级以上」。用户同意后用 `$tutti-bug-workflow:bug-solution`／`$tutti-bug-workflow:bug-execute` 的「定时任务管理」开启，并告诉用户先看一眼当前有几条待处理。
- **QA 提 Bug**：告诉用户怎么用：在本机 Codex 里说「记个 bug：<现象>」，带上 Room 链接和截图即可；Task 用 `tutti-cli login` 登录的账号建在该 Room，创建后在任务看板指派跟进人。

## 默认配置

以下都有默认值，用户不需要提供；要改就告诉 Agent 或编辑数据目录的 `config.json`，详见 [配置说明](references/configuration.md)。

| 配置 | 默认值 |
|---|---|
| 数据目录 | `~/.local/share/bug-workbench`（可用 `BUG_WORKBENCH_DATA` 改） |
| Bug 表 | 飞书「需求及 Bug 管理 底表」→「Bug 管理」，视图「新框架（一期）」，全部字段映射见 [字段与职责](references/report-fields.md) |
| 代码仓库 | tutti、tutti-server、tsh-websocket 的 main，缓存在数据目录 `repositories/` |
| 定时分析 | 每小时一轮，单条会话 45 分钟上限，运行记录保留 7 天 |
| 定时修复 | 每小时一轮，单条会话 180 分钟上限，运行记录保留 7 天；分支 `codex/bug-<record>`，泳道 `ppe-bug-<record>` |
| PPE 部署 | tutti-server／tsh-websocket `deploy-lane.yml`，前端 `platform-web-preview.yml`，Computer `computer-artifacts-release.yml`；连接器授权默认关闭 |
| 定时任务跟进人 | 当前飞书登录用户；不限优先级 |
| tutti-ops 管理端 | `https://admin.tutti.sh` |
| 本机 Computer 日志 | `~/.tutti-amp/computer/logs/` 下的 companion、desktopd、runtime-host 日志，以及 `${TMPDIR}/tutti-codex-appserver-startup.jsonl` |
| AWS | 当前凭证链，区域 `us-east-1`（只在 bug-execute 选 AWS 日志时用；提 Bug 不需要） |

## 可选与参考

- **AWS 服务端日志**：提 Bug 不需要（只记 request id）；修复时用户明确要用才加 `--include aws`，安装与登录见 [AWS CLI](references/aws-cli.md)。
- 单项工具命令仍可直接用：`scripts/workbench.py doctor`、`setup-tutti-ops --install`、`configure-tutti-token --admin-url https://admin.tutti.sh`、`setup-aws-cli --install|--check-auth`、`configure-mcp`。
- 引导话术与各入口的授权细节：[易懂的准备与授权流程](references/setup-user-guide.md)。
- 各能力的背景：[Web 日志](references/web-logs.md)、[tutti-ops 获取日志](references/tutti-ops-computer-logs.md)、[Computer 日志](references/computer-logs.md)、[提 Bug 后的会话上传](references/session-upload.md)、[代码缓存](references/repository-cache.md)、[工具目录](references/tool-setup.md)、[工作流与交接](references/workflow.md)。
