# tutti-bug-workflow

版本：0.6.1。运行方式：Codex 本地会话。四个 Skill：QA 提 Bug、验收打回、修复与部署、环境准备。只对接 Tutti 任务系统：Bug 是 Room 里的 Task，用全局 `tutti-cli` 读写；不用飞书表，也没有定时任务，都由人手动触发。

| 入口 | 工作内容 |
|---|---|
| `$tutti-bug-workflow:bug-investigate` | QA 提 Bug：带全现场日志与上下文，用全局 tutti-cli 在指定 Room 建 Task、补全描述和附件并回读确认，完成登记，不自动触发 Agent 执行 |
| `$tutti-bug-workflow:bug-reopen` | 验收打回：QA 发来已有 Task 链接和截图、说这里还有问题时，和提 Bug 一样采集这一轮的现场，在原 Task 下发打回评论（截图、日志作为评论附件），把 Task 改回待办，再交给该 Room 的 Agent 重新分析 |
| `$tutti-bug-workflow:bug-execute` | 修复与部署：RD 指定一条 Bug Task 和认可的方案，修复、提 PR 到 main，部署 PPE（server 泳道 → ws 泳道 → 前端预览 → Computer canary），自验证，结果回复到 Task |
| `$tutti-bug-workflow:bug-setup` | 准备环境：选场景（QA 提 Bug／修复与部署），自动检查、安装、补默认配置，一步步引导登录和授权 |

## 首次使用

安装说明见分发目录根部的 README。安装后在 Codex 里说：

> 使用 $tutti-bug-workflow:bug-setup 帮我准备环境

Agent 会先问你要准备哪个场景：**QA 提 Bug**、**修复与部署**，或**全部**。之后：

1. **检查**：`skills/bug-setup/scripts/prepare.py check --scene …` 逐项实际验证。QA 提 Bug：Node.js、tutti-cli 安装与登录、tutti-ops Token、本机 Chrome 连接、本机 Computer 日志；修复与部署：tutti-cli 安装与登录、三个仓库、GitHub 登录与推送／部署权限、本机 Chrome 连接。
2. **能做的直接做**：`prepare.py fix` 补齐默认配置（已有值不动，原文件备份），用 npm 把 tutti-cli（Node.js 24+）装成或升级到最新版，安装缺少的 tutti-ops，用 Homebrew 安装 gh。
3. **一步步引导**：需要你本人做的（`tutti-cli login`、`gh auth login`、管理端创建 Token、Chrome 点允许、找管理员要权限），一次一项给出步骤和可复制的命令，你回复「已完成」后 Agent 复查。
4. **收尾**：汇总已就绪／等你／等管理员；告诉你两个场景怎么用。

只想先看看要准备什么：「使用 $tutti-bug-workflow:bug-setup，只列出准备情况」。

默认配置（三个仓库、修复分支与泳道命名、PPE 部署、tutti-ops 管理端、本机 Computer 日志路径等）都已内置，不需要你提供，见 [Setup Skill](skills/bug-setup/SKILL.md#默认配置)。数据目录默认 `~/.local/share/bug-workbench`（可用 `BUG_WORKBENCH_DATA` 覆盖），配置与运行记录都在这里，插件更新不影响。单项工具命令（`workbench.py doctor`、`setup-tutti-ops`、`configure-tutti-token`）仍可直接使用，见 [准备与授权教程](skills/bug-setup/references/setup-user-guide.md)。

## QA 提 Bug（`bug-investigate`）

用全局安装的 `tutti-cli`（npm `@tutti-os/tutti-cli`，Node.js 24+，`tutti-cli login` 用浏览器登录 Tutti 账号）在 QA 指定的 Room 建 Task。在 QA 本机的 Codex 会话里运行；带全现场、补全 Task 并回读确认后完成登记，后续由 RD 跟进，不自动触发 Agent 执行。流程见 [SKILL.md](skills/bug-investigate/SKILL.md)：

1. 接收上报，判断所属端、优先级、业务模块，生成 `operation_id`（即 Task ID 与幂等键）；上报时间和故障发生时间分开记，日志按故障时间取（QA 晚报也能取到当时的现场）。
2. `find_room.py` 用 `tutti-cli room list` 按 QA 给的 Room ID／链接、房间名或用户名找房间（本地房间优先，多个候选时请 QA 选），`task create --room-id` 按 QA 描述先建 Task（优先级只能在此时设置）。
3. Web 日志：本机 Chrome WebMCP 通过 `download_web_logs` 一次下载完整日志（工具仅返回元数据，`merge_web_logs.py --download` 在本地校验、整理），不可用时用 QA 导出的诊断包；并行跑 Computer 召回（`collect_computer.py`，后台）；`web_requests.py` 列出失败请求及其 request id（`x-zk-request-id`），连同 Computer 日志里失败出站请求的 request id 写进排查线索。提 Bug 不查服务端日志、不依赖 AWS，RD 排查时再按 request id 查。
4. 现场齐了以后一次 `task edit`：标题改成一句话 Bug 简介，描述只写 Bug 表现（问题、复现步骤、实际、期望），截图、`排查线索.txt`（日志核对、关联 ID、环境与版本）和全部日志用 `--file` 作为 Task 私有附件挂上；`task show` 回读。
5. 缺的一次问完，用户补充后带上全部文件再 `task edit` 一次；复用已有 Task 时用普通评论追加现场，不带 `--agent-target-id`。CLI 不能指派，请 QA 在任务看板指派跟进人。最后上传本次会话，交付 Task 链接。

## 验收打回（`bug-reopen`）

QA 手动触发，一次一条 Task，在 QA 本机的 Codex 会话里运行。不用说固定的词：发已有 Task 的链接，配上截图或一句「这里还有问题，打回去」即可；在提 Bug 的同一个会话里说「之前提的 bug 还有问题，加个评论打回去」也行，不用链接，Task 从会话上下文里取（本会话提过多条时请 QA 选）。同一个会话里 Task 还没修过（`todo`／`in_progress`）时，QA 的补充仍按提 Bug 更新描述。没有 Task 的新问题仍走提 Bug。流程见 [SKILL.md](skills/bug-reopen/SKILL.md) 与 [打回评论与附件](skills/bug-reopen/references/reopen-comment.md)：

1. 对 agent 说「<Task 链接> 这里还有问题，打回去」，带上截图。`tutti-cli task show` 读原 Task，记下标题、描述和打回前的状态。
2. 和提 Bug 一样采集这一轮验收的现场：Web 日志通过 `download_web_logs` 直接下载文件，再由本地脚本校验和读取；不可用时用 QA 诊断包。后台跑 Computer 召回，`web_requests.py` 列出失败请求的 request id；不查服务端日志。
3. 用 `tutti-cli task comment --file` 在原 Task 下发一条打回评论：正文写验收版本、复现步骤、实际、期望、和修复前相比，截图、`排查线索.txt` 和全部日志作为评论附件。不用 `task edit`，原描述和第一轮现场附件保持不变。
4. 用 `tutti-cli task status --status todo` 把 Task 改回待办（需要 tutti-cli 0.1.3+），`task show` 回读；没有权限时请 QA 在任务看板拖回待办。
5. 默认用 `task run --reply-to <打回评论>` 在打回评论的线程里交给该 Room 的 Agent 重新分析（Codex 优先，其次 Claude Code），指令要求先说清上一轮修复为什么没生效，再重新分析根因、出方案、画流程图；确认受理后就不管了。QA 说「只打回、不用分析」时跳过。见 [交给 Room Agent 重新分析](skills/bug-reopen/references/rd-reanalysis.md)。
6. 后到的现场回复在打回评论的线程里，只带新文件，不重发分析指令；最后上传本次会话。

## 修复与部署（`bug-execute`）

RD 手动触发，一次一条 Task，流程见 [SKILL.md](skills/bug-execute/SKILL.md) 与 [PPE 部署](skills/bug-execute/references/deploy.md)：

1. 对 agent 说「修复这个 Task <链接>」，并贴上认可的方案（通常是 Room Agent 在 Task 里回复的根因分析；`tutti-cli` 读不到评论，所以要贴过来）。`tutti-cli task show` 读 Task 的 Bug 表现。
2. 从最新 main 切 `codex/bug-<Task ID 前 8 位>`（重试时接着原分支）→ 修复、测试 → 推送、提 PR 到 main。
3. 部署 PPE：先 tutti-server `deploy-lane`（泳道 `ppe-bug-<同样 8 位>`，关闭连接器授权），涉及 ws 时 tsh-websocket `deploy-lane`（同一泳道；新泳道需人工先建 ws 基础设施），再 tutti `platform-web-preview`（指向该泳道），涉及 Computer 时在分支上发 `Computer Canary`。
4. 用本机 Chrome（chrome-devtools MCP）打开预览链接，按验收要点自验证，涉及 UI 的每条用例截图。
5. 用 `tutti-cli task comment` 把一句话原因、PR、体验链接（前端预览，只改 Computer 时为 canary 发布页）和验证结果回复到 Task，验证截图作为评论附件一起上传；失败也回复，写清卡在哪一步。
6. 泳道不自动销毁，需要时让 agent 用 `deploy.py destroy-lane` 销毁。

## 已提供的能力

- 四个可发现的 Skills：bug-investigate（QA 提 Bug）、bug-reopen（验收打回）、bug-execute（修复与部署）和 bug-setup（环境准备），都只对接 Tutti 任务系统。
- 幂等初始化、环境检查、私有目录下的固定版本 npm CLI 安装。
- setup 复用已有 tutti-ops，缺少时按 `npm install -g @tutti-os/tutti-ops-cli` 全局安装，记录实际版本和入口；根据已安装命令的帮助与 schema 读取 Computer。
- 从实际配置生成便携 MCP 配置与旧版 Codex 兼容配置。

tutti-ops 使用用户指定的全局 npm 安装方式，要求 Node.js >=20 和 npm，详见 [tutti-ops 安装与认证](skills/bug-setup/references/tutti-ops-computer-logs.md)。其他 CLI 先填写可信 npm 包名与精确版本，再显式调用 `install-cli`；通用私有 npm 安装器不运行包的安装脚本，其他原生工具按实际安装方法适配。

插件不自带 MCP server（chrome-devtools 除外）。setup 不安装、不登录 AWS。其他 MCP 填写真实服务后使用 `configure-mcp --config CONFIG --output-dir PLUGIN_SOURCE` 生成配置，再通过安装流程更新插件。配置生成不代表服务已经部署、登录或连接成功。

Web 日志由 QA 在出问题的浏览器里自行导出：Tutti「设置 → 诊断 → 浏览器日志」选择覆盖故障时间的范围，点「导出日志」，得到 `tutti-web-diagnostics-<时间>.zip`（`manifest.json`、`errors.jsonl`、`logs.jsonl`，已脱敏）。Agent 把这个包原样作为 Task 附件上传，再解包阅读；QA 没附带时，排查到需要时连同其他问题一起请 QA 导出。详见 [Web 日志](skills/bug-investigate/references/web-logs.md)。

远端 Computer 日志通过 [tutti-ops CLI](skills/bug-investigate/references/tutti-ops-computer-logs.md) 定位 Computer、复用或创建召回、查询任务和生成链接，再下载、校验并读取日志包。setup 准备 CLI，使用前从 [admin.tutti.sh](https://admin.tutti.sh) 管理端获取 Token，通过 `configure-tutti-token` 隐藏输入，直接验证并保存到 CLI 本机配置，再核对实际环境与权限；当前 npm 包的原子操作已通过帮助、schema 和零网络预览验证，组合采集命令仅在实际发现后使用。

## 当前接入范围

QA 提 Bug 用全局 tutti-cli 在指定 Room 建 Task。Web 日志使用 QA 导出的诊断包，见 [Web 日志](skills/bug-investigate/references/web-logs.md)。本地 computer 日志读取用户指定的明确文件路径；远端 computer 固定复用 Tutti 的日志召回流程，可使用 tutti-ops CLI 或实际 MCP 执行，见 [Computer 日志获取](skills/bug-investigate/references/computer-logs.md)。当前 Mac 已保存核实的三个本地主日志及 Codex 临时诊断路径，并记录轮转日志、VM 崩溃报告与导出漏收注意事项；其他机器需确认实际路径。本机 tutti-ops 已安装并完成离线能力核对，远端认证与真实日志采集尚待验证；其他使用者的宿主能力、远端环境／权限及验证地址仍需分别核对。Skills 可复用当前 Codex 会话的本地工具与已连接 MCP；当前包没有自带 MCP server 或常驻调度服务。共享此包携带仓库地址，不授予收件人访问权限，也不携带本机检出路径或凭证。

本地执行仍可能把选取的代码、日志片段和工具输出提交给模型。共享源码和分发包不包含真实业务数据或凭证。

提 Bug 不拉服务端日志：Web 与 Computer 日志里的请求都带网关 request id，记进排查线索，RD 排查时再按 id 查 tutti-server 日志。

## 验证插件源码

```sh
python3 PLUGIN_SOURCE/scripts/validate_plugin.py
for skill in skills/bug-investigate skills/bug-reopen skills/bug-setup skills/bug-execute; do
  python3 -m unittest discover -s PLUGIN_SOURCE/$skill/tests -t PLUGIN_SOURCE/$skill/tests
done
```

打包时包括根部 `plugin.json`、`mcp.json`、`skills/` 和隐藏兼容文件。排除业务数据、凭证、工具安装目录与缓存。
