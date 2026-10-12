# tutti-bug-workflow

版本：0.1.49。运行方式：Codex 本地会话。三个业务场景以飞书 Bug 管理表中的同一条记录交接，不保留本地档案；公共初始化 Skill 准备配置与依赖。

| 入口 | 工作内容 |
|---|---|
| `$tutti-bug-workflow:bug-investigate` | QA 提 Bug：登记并带全现场日志与上下文，不分析根因 |
| `$tutti-bug-workflow:bug-solution` | RD 根因与方案（定时）：每小时按跟进人逐条分析根因、生成流程图与架构图 PNG、起草方案和验收，记录 RD 批准 |
| `$tutti-bug-workflow:bug-execute` | 修复与部署（定时）：每小时按跟进人修复已批准的 Bug，提 PR 到 main，部署 PPE（server 泳道 → ws 泳道 → 前端预览 → Computer canary），验证，进度写回 bug 单 |
| `$tutti-bug-workflow:bug-setup` | 准备环境：选场景，自动检查、安装、补默认配置，一步步引导登录和授权，可直接开启定时任务 |

## 首次使用

安装说明见分发目录根部的 README。安装后在 Codex 里说：

> 使用 $tutti-bug-workflow:bug-setup 帮我准备环境

Agent 会先问你要准备哪个场景：**QA 提 Bug**、**定时分析**、**定时修复**，或**全部**（RD 一般选定时分析＋定时修复）。之后：

1. **检查**：`skills/bug-setup/scripts/prepare.py check --scene …` 逐项实际验证：飞书登录与 Bug 表、三个仓库、Codex 登录、mmdc 渲染、GitHub 登录与推送/部署权限、tutti-ops Token、本机 Chrome 连接、定时任务。
2. **能做的直接做**：`prepare.py fix` 补齐默认配置（已有值不动，原文件备份），用 npm／Homebrew 安装缺少的 lark-cli、codex、mmdc、tutti-ops、gh。
3. **一步步引导**：需要你本人做的（飞书扫码授权、`gh auth login`、`codex login`、管理端创建 Token、Chrome 点允许、找管理员要权限），一次一项给出步骤和可复制的命令，你回复「已完成」后 Agent 复查。
4. **收尾**：汇总已就绪／等你／等管理员，询问是否开启定时任务（默认跟进人是你，每小时一轮，不限优先级）。

只想先看看要准备什么：「使用 $tutti-bug-workflow:bug-setup，只列出准备情况」。

默认配置（Bug 表与字段、三个仓库、定时任务、PPE 部署、tutti-ops 管理端、本机 Computer 日志路径等）都已内置，不需要你提供，见 [Setup Skill](skills/bug-setup/SKILL.md#默认配置)。数据目录默认 `~/.local/share/bug-workbench`（可用 `BUG_WORKBENCH_DATA` 覆盖），配置、代码缓存与运行记录都在这里，插件更新不影响。单项工具命令（`workbench.py doctor`、`setup-tutti-ops`、`configure-tutti-token`、`setup-aws-cli`）仍可直接使用，见 [准备与授权教程](skills/bug-setup/references/setup-user-guide.md)。

## 飞书 Bug 管理表

三个场景共用 [Bug 管理表（视图「新框架（一期）」）](https://ccn53rwonxso.feishu.cn/base/CEHMbNF8Zavq5wsAO3ecrpQ6nPc?table=tblieImZwMnvZ8My&view=vewoD2kiPo)，每个场景只写自己负责的字段，「状态」由人工流转。「方案状态」串起后两个场景：空／未处理／已驳回 → 定时分析 → 待评审 → RD 选已批准或已驳回（写驳回意见，重新分析）→ 定时修复 → 修复中 → 已部署待验收／修复失败。字段与职责见 [字段与职责](skills/bug-setup/references/report-fields.md)。

| 场景 | 写入的字段 |
|---|---|
| bug-investigate | Bug 描述、所属端、优先级、业务模块、提交人、指派人、记录时间、环境与版本、页面链接、问题上下文、截图／视频／日志 |
| bug-solution | 分析根因、根因图（PNG）、修复方式、验收标准；方案状态置「待评审」 |
| bug-execute | 方案状态（修复中／已部署待验收／修复失败）、修复进度、访问环境、一句话解释原因、关联 PR、验证结果、修复截图 |

### QA 提 Bug（`bug-investigate`）

不做根因分析，只把当时的现场带全，写进飞书 Bug 管理表（视图「新框架（一期）」）。无状态：流程状态只在会话上下文中，飞书记录是唯一事实来源。流程见 [SKILL.md](skills/bug-investigate/SKILL.md)：

1. 接收上报，判断所属端、优先级、业务模块，`feishu.py create` 建单，`assign` 写跟进人。
2. Web 日志：本机 Chrome WebMCP 读页面日志（`merge_web_logs.py` 合并），不可用时用 QA 导出的诊断包。
3. 并行：Computer 召回（`collect_computer.py`，后台）与 Server 日志（`collect_server.py`，subagent，从 Web 日志提取 request id 查 AWS CloudWatch 并识别生产／PPE）。
4. 上传截图、视频与全部日志，写入环境与版本、页面链接、问题上下文；全部完成后上传本次会话。

### 根因与方案（`bug-solution`）

定时分析，流程见 [SKILL.md](skills/bug-solution/SKILL.md) 与 [定时任务](skills/bug-solution/references/schedule.md)：

1. 对 agent 说「给张三开 bug 根因定时分析，只看 P1 以上」，`schedule.py install` 为该跟进人装一个本机 launchd 任务，每小时一轮。
2. 每轮 `scan.py`：列出该跟进人「未解决」且方案状态为空／未处理／已驳回的 Bug，同步全局代码检出到最新 main，全部处理。
3. 每条 Bug 一个 `codex exec` 会话（本机运行，不进 sandbox），运行目录里备好 `context.md`（记录全部字段，被驳回时含驳回意见和上一版）、附件和代码 SHA；会话写「分析根因」「修复方式」「验收标准」，渲染流程图、架构图 PNG 上传「根因图」，最后把方案状态置「待评审」。写入带守卫，RD 已评审的不覆盖。
4. RD 在飞书评审：选「已批准」进入 bug-execute，选「已驳回」并写驳回意见，下一轮重新分析。

### 修复与部署（`bug-execute`）

定时修复，流程见 [SKILL.md](skills/bug-execute/SKILL.md)、[定时任务](skills/bug-execute/references/schedule.md) 与 [PPE 部署](skills/bug-execute/references/deploy.md)：

1. 对 agent 说「给张三开定时修复」，`schedule.py install` 为该跟进人装一个本机 launchd 任务，每小时一轮。
2. 每轮 `scan.py`：遗留的「修复中」标为修复失败；方案状态为「已批准」的 Bug 逐条置「修复中」，各起一个 `codex exec` 会话（本机运行，不进 sandbox）。
3. 会话：从最新 main 切 `codex/bug-<record_id>`（重试时接着原分支）→ 修复、测试 → 推送、提 PR 到 main → 部署 PPE：先 tutti-server `deploy-lane`（泳道 `ppe-bug-<record_id>`，关闭连接器授权），涉及 ws 时 tsh-websocket `deploy-lane`（同一泳道；新泳道需人工先建 ws 基础设施），再 tutti `platform-web-preview`（指向该泳道），涉及 Computer 时在分支上发 `Computer Canary`，部署成功后把前端预览链接（只改 Computer 时为 canary 发布页）回填到「访问环境」，点开即可体验 → 用本机 Chrome（chrome-devtools MCP）打开预览链接按验收标准自验证，涉及 UI 的每条用例截图上传到「修复截图」 → 写验证结果，方案状态置「已部署待验收」；任何一步失败置「修复失败」。每一步写进「修复进度」。
4. 泳道不自动销毁，需要时让 agent 用 `deploy.py destroy-lane` 销毁。

## 已提供的能力

- 四个可发现的 Skills；其中三个是业务场景。
- 根因、方案、验收与验证模板。
- 幂等初始化、环境检查、私有目录下的固定版本 npm CLI 安装。
- setup 复用已有 tutti-ops，缺少时按 `npm install -g @tutti-os/tutti-ops-cli` 全局安装，记录实际版本和入口；根据已安装命令的帮助与 schema 读取 Computer。
- setup 准备 AWS CLI v2，复用已有安装，缺少时通过 AWS 官方安装器补齐；完整 Setup 接续身份检查和缺口处理，完成必要的本人操作后复查实际访问。
- bare 代码缓存增量同步、全局分析检出、修复 worktree 的创建／推送／解除，均加文件锁。
- 按跟进人安装的本机定时根因分析（launchd + codex exec），Mermaid 图渲染 PNG。
- 从实际配置生成便携 MCP 配置与旧版 Codex 兼容配置。
- 执行前确认方案状态为「已批准」且根因、方案、验收齐全。

AWS CLI 使用专用官方安装器，新安装固定版本，核对安装脚本摘要和最终版本，详见 [AWS CLI 安装](skills/bug-setup/references/aws-cli.md)。tutti-ops 使用用户指定的全局 npm 安装方式，要求 Node.js >=20 和 npm，详见 [tutti-ops 安装与认证](skills/bug-setup/references/tutti-ops-computer-logs.md)。其他 CLI 先填写可信 npm 包名与精确版本，再显式调用 `install-cli`；通用私有 npm 安装器不运行包的安装脚本，其他原生工具按实际安装方法适配。

插件不自带 MCP server；AWS 默认使用 CLI。确认 CLI 可用后，仅清理由旧插件创建且未被改动的 AWS MCP，保留其他连接。AWS MCP 仅在用户明确要求恢复时按 [兼容接入](skills/bug-setup/references/aws-mcp.md) 配置。其他 MCP 填写真实服务后使用 `configure-mcp --config CONFIG --output-dir PLUGIN_SOURCE` 生成配置，再通过安装流程更新插件。配置生成不代表服务已经部署、登录或连接成功。

Web 日志由 QA 在出问题的浏览器里自行导出：Tutti「设置 → 诊断 → 浏览器日志」选择覆盖故障时间的范围，点「导出日志」，得到 `tutti-web-diagnostics-<时间>.zip`（`manifest.json`、`errors.jsonl`、`logs.jsonl`，已脱敏）。Agent 把这个包原样上传到 Bug 单，再解包阅读；QA 没附带时，排查到需要时连同其他问题一起请 QA 导出。详见 [Web 日志](skills/bug-investigate/references/web-logs.md)。

远端 Computer 日志通过 [tutti-ops CLI](skills/bug-investigate/references/tutti-ops-computer-logs.md) 定位 Computer、复用或创建召回、查询任务和生成链接，再下载、校验并读取日志包。setup 准备 CLI，使用前从 [admin.tutti.sh](https://admin.tutti.sh) 管理端获取 Token，通过 `configure-tutti-token` 隐藏输入，直接验证并保存到 CLI 本机配置，再核对实际环境与权限；当前 npm 包的原子操作已通过帮助、schema 和零网络预览验证，组合采集命令仅在实际发现后使用。

## 当前接入范围

飞书 Bug 管理表及字段已绑定，并在本机通过 user 身份读取验证。三个仓库（tutti、tutti-server、tsh-websocket）的 URL 与 main 分支已配置。Web 日志使用 QA 导出的诊断包，见 [Web 日志](skills/bug-investigate/references/web-logs.md)。本地 computer 日志读取用户指定的明确文件路径；远端 computer 固定复用 Tutti 的日志召回流程，可使用 tutti-ops CLI 或实际 MCP 执行，见 [Computer 日志获取](skills/bug-investigate/references/computer-logs.md)。当前 Mac 已保存核实的三个本地主日志及 Codex 临时诊断路径，并记录轮转日志、VM 崩溃报告与导出漏收注意事项；其他机器需确认实际路径。本机 tutti-ops 已安装并完成离线能力核对，远端认证与真实日志采集尚待验证；其他使用者的宿主能力、远端环境／权限及验证地址仍需分别核对。Skills 可复用当前 Codex 会话的本地工具与已连接 MCP；当前包没有自带 MCP server、飞书连接器或常驻调度服务。共享此包携带表格和仓库地址，不授予收件人访问权限，也不携带本机检出路径或凭证。

飞书事件触发、重试、事件去重、跨设备调度与可信 RD 审批属于后续流程服务，契约见 [工作流](skills/bug-setup/references/workflow.md)。本版 `check-approval` 以方案状态为准，谁批准的以飞书修改记录为准。

本地执行仍可能把选取的代码、日志片段和工具输出提交给模型。共享源码和分发包不包含真实业务数据或凭证。

服务端日志判断必需或建议补／可辅助后，在本轮立即调用实际Tutti CLI或已确认AWS来源的AWS CLI，先保存易失证据，追加上传同一条Bug并回读；不会停在建议或等待QA追问。成功访问记录不能用HTTP失败归因空结果代替。详见 [服务端日志](skills/bug-investigate/references/server-logs.md)。

## 验证插件源码

```sh
python3 PLUGIN_SOURCE/scripts/validate_plugin.py
for skill in bug-investigate bug-setup bug-solution bug-execute; do
  python3 -m unittest discover -s PLUGIN_SOURCE/skills/$skill/tests -t PLUGIN_SOURCE/skills/$skill/tests
done
```

打包时包括根部 `plugin.json`、`mcp.json`、`skills/` 和隐藏兼容文件。排除业务数据、凭证、工具安装目录与缓存。
