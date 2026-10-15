---
name: bug-setup
description: 准备 tutti-bug-workflow 的运行环境：先让用户选场景（QA 提 Bug／根因分析／修复与部署／全部），自动检查、安装能装的工具、补齐默认配置并把技能同步到本机 Multica 的三个 Agent，需要本人操作的登录和授权一步步引导、完成后复查；也支持只列出准备情况。Bug 记录在 Multica issue。
---

# 准备工作台

QA 提 Bug（`$tutti-bug-workflow:bug-investigate`）、根因分析（`$tutti-bug-workflow:bug-analyze`）和修复与部署（`$tutti-bug-workflow:bug-execute`）共用的准备入口：**选场景 → 检查 → 能做的直接做 → 一步步引导本人操作 → 复查收尾**。目标是用户只需要做必须本人做的事（登录、授权、找管理员要权限），其余 Agent 全部完成。

脚本路径相对本 Skill 目录（`skills/bug-setup/`），都输出一段 JSON。配置和运行数据在数据目录（默认 `~/.local/share/bug-workbench`），插件更新不影响。

## 1. 选场景

用户已经说清楚（「准备 QA 提 Bug 的环境」「准备修 Bug 的环境」）就直接用；否则**先问这一个问题**，其他都不用问：

> 要准备哪个场景？
> 1. **QA 提 Bug**：自动采集页面和 Computer 现场日志，在 Multica 登记 issue，交给分析 Agent
> 2. **根因分析**：分析 Agent 拉最新代码找根因、出方案，回复在 issue 里等 RD 评审
> 3. **修复与部署**（RD）：认可方案后把 issue 分配给修复 Agent，提 PR、部署 PPE、自验证，结果回复到 issue
> 4. **全部**（三个 Agent 都在这台机器上跑时选它）

用户说「我是 QA」按 1；「我是 RD」按 2、3；拿不准建议「全部」。场景对应 `--scene investigate`／`analyze`／`execute`／`all`，可重复。

Bug 记录在 Multica：三个场景分别由 Multica 里的三个 Agent 在本机 Codex runtime 上执行，靠分配 issue 交接，见 [Multica 接入](references/multica.md) 和 [工作流](references/workflow.md)。

## 2. 检查

```sh
python3 scripts/prepare.py check --scene all   # 按选的场景
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
python3 scripts/prepare.py fix --scene all
```

它会：用默认配置补齐数据目录的 `config.json`（只补缺的项，已有值不动，原文件备份为 `config.before-prepare.json`）；用 npm 安装缺少的 tutti-ops；三个 Agent 都在时运行 `multica.py sync --prune`，把插件源码里的三个技能同步到 Multica workspace、分配给对应 Agent 并更新 Agent 指令（见 [Multica 接入](references/multica.md)）。然后自动复查。

`fix_errors` 里的失败先自己处理：npm 全局目录没有写权限时改用 nvm 的 Node；网络失败重试一次；仍然不行就转成 `user` 项，写清原因和用户要做的事。

`user` 项里 Agent 能先做的部分也直接做，用户只做最后那一下：

| 项 | Agent 先做 | 用户做 |
|---|---|---|
| Multica 未安装或未登录 | 给出 Multica 桌面端下载地址 | 安装并登录桌面端，回复「已完成」 |
| Multica 项目、Agent 缺失或 runtime 不在线 | 列出缺的项目和 Agent 名称、要绑定的本机 Codex runtime | 在 Multica 里创建，回复「已完成」；Agent 名称不同时告诉 Agent 改配置 |
| GitHub 登录（修复与部署） | 给出 `gh auth login -h github.com -s repo,workflow` | 在终端运行，按提示在浏览器授权，回复「已完成」 |
| Chrome 连接（`host`） | 调用 chrome-devtools 的 `list_pages` 和 `list_webmcp_tools` | Chrome 弹窗点「允许」；没开远程调试或 WebMCP flag 时按 `guide` 打开 |
| tutti-ops Token | 准备好 `configure-tutti-token` 命令 | 在管理端创建 Token，在终端隐藏粘贴 |

## 4. 一步步引导本人操作

按顺序**一次只引导一项**：Multica → GitHub → tutti-ops → Chrome → 需要管理员的权限（只引导所选场景用得到的）。每项都这样说：

1. **为什么**：一句话说用途（「Bug 记录在 Multica，三个 Agent 在你这台机器上跑」「为了推送修复分支、触发 PPE 部署」）。
2. **你要做什么**：照 `guide` 写成编号步骤；要在终端运行的命令给出完整、可直接复制的一行；网页给出真实链接。
3. **做完回复「已完成」**，我来检查。

能由 Agent 发起、只需用户在浏览器里点一下的登录（上表），不要让用户回复，命令返回后直接复查。收到「已完成」后重新 `check`，以实际结果为准；通过就进入下一项，没通过就说明这次具体卡在哪、下一步怎么做。

- Token、密码、App Secret 只在用户本机的隐藏输入里出现，不要让用户发到对话里，也不写进配置或 issue。
- 需要管理员处理的（管理端账号、Multica workspace 成员身份、GitHub 仓库写权限与部署权限）：告诉用户找谁、要什么权限，然后继续其他项，不卡住整个流程。
- 不用试建 issue、推送、部署来测试权限；不自己给自己加权限。

## 5. 收尾

再跑一次 `check`，用一张表交付：每个场景「已就绪／等你操作／等管理员」，以及受影响的能力。

- **QA 提 Bug**：在 Multica 的 Bug 项目里建 issue（写现象，附截图），分配给登记 Agent；或在本机 Codex 里说「记个 bug：<现象>」。登记完会自动交给分析 Agent。
- **根因分析**：不用手动触发；分析结果回复在 issue 里，状态变为 `in_review`。RD 有问题直接在 issue 里评论。
- **修复与部署**：RD 认可方案后，把 issue 分配给修复 Agent（评论里可写明采用哪个方案）；修复结果和验证截图会回复到 issue。也可以在本机 Codex 里说「修复这个 issue <编号>」。

## 默认配置

以下都有默认值，用户不需要提供；要改就告诉 Agent 或编辑数据目录的 `config.json`，详见 [配置说明](references/configuration.md)。

| 配置 | 默认值 |
|---|---|
| 数据目录 | `~/.local/share/bug-workbench`（可用 `BUG_WORKBENCH_DATA` 改） |
| Multica | profile `desktop-api.multica.ai`，项目 `Bug列表`，Agent 噜噜Bug守门员／噜妹Bug分析师／牛牛Bug解决专员 |
| 代码仓库（修复与部署） | tutti、tutti-server、tsh-websocket 的 main，缓存在数据目录 `repositories/` |
| 修复分支与泳道 | 分支 `codex/bug-<issue 编号小写>`，泳道 `ppe-bug-<同样>` |
| PPE 部署 | tutti-server／tsh-websocket `deploy-lane.yml`，前端 `platform-web-preview.yml`，Computer `computer-artifacts-release.yml`；连接器授权默认关闭 |
| tutti-ops 管理端 | `https://admin.tutti.sh` |
| 本机 Computer 日志 | `~/.tutti-amp/computer/logs/` 下的 companion、desktopd、runtime-host 日志，以及 `${TMPDIR}/tutti-codex-appserver-startup.jsonl` |

## 可选与参考

- 单项工具命令仍可直接用：`scripts/workbench.py doctor`、`setup-tutti-ops --install`、`configure-tutti-token --admin-url https://admin.tutti.sh`、`configure-mcp`。
- 引导话术与各入口的授权细节：[易懂的准备与授权流程](references/setup-user-guide.md)。
- 各能力的背景：[Web 日志](references/web-logs.md)、[tutti-ops 获取日志](references/tutti-ops-computer-logs.md)、[Computer 日志](references/computer-logs.md)、[提 Bug 后的会话上传](references/session-upload.md)、[工具目录](references/tool-setup.md)、[代码缓存](references/repository-cache.md)、[Multica 接入](references/multica.md)、[工作流与交接](references/workflow.md)。
