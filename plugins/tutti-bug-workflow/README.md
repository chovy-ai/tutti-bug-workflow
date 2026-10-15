# tutti-bug-workflow

版本：0.6.0。四个 Skill：QA 提 Bug、根因分析、修复与部署、环境准备。**Bug 记录在 Multica**：一条 Bug 一个 issue，三个业务 Skill 分别由本机 Multica 的三个 Agent（绑定本机 Codex runtime）执行，靠分配 issue 交接；也可以在本机 Codex 会话里直接调用。

| 入口 | Multica Agent（默认名称） | 工作内容 |
|---|---|---|
| `$tutti-bug-workflow:bug-investigate` | 噜噜Bug守门员 | QA 提 Bug：带全现场日志与上下文，在 Bug 项目里登记 issue，现场作为附件发在「现场材料」评论里，然后分配给分析 Agent |
| `$tutti-bug-workflow:bug-analyze` | 噜妹Bug分析师 | 根因分析：拉最新代码找根因，回复根本／兼容方案、修复前后流程图和验收要点，状态 `in_review` 等 RD 评审 |
| `$tutti-bug-workflow:bug-execute` | 牛牛Bug解决专员 | 修复与部署：RD 认可方案后分配给它，修复、提 PR 到 main，部署 PPE（server 泳道 → ws 泳道 → 前端预览 → Computer canary），自验证，结果和截图回复到 issue |
| `$tutti-bug-workflow:bug-setup` | — | 准备环境：选场景，自动检查、安装、补默认配置，把三个技能同步到 Multica 的三个 Agent，一步步引导登录和授权 |

```text
QA 建 issue 分配给守门员（或说「记个 bug」）→ 守门员登记、发现场，分配给分析师
→ 分析师回复根因与方案（in_review）→ RD 评审：评论追问，认可后分配给解决专员
→ 解决专员修复、部署 PPE、自验证，回复结果与截图（in_review／blocked）→ QA 验收（done）
```

## 首次使用

安装说明见分发目录根部的 README。先在 Multica 桌面端登录，建好项目「Bug列表」和三个 Agent（运行环境选本机的 Codex runtime），再在 Codex 里说：

> 使用 $tutti-bug-workflow:bug-setup 帮我准备环境

Agent 会先问你要准备哪个场景：**QA 提 Bug**、**根因分析**、**修复与部署**，或**全部**。之后：

1. **检查**：`skills/bug-setup/scripts/prepare.py check --scene …` 逐项实际验证：Multica 登录、项目、三个 Agent 与 runtime、技能是否与插件源码一致；QA 提 Bug 另查 Node.js、tutti-ops Token、本机 Chrome、本机 Computer 日志；分析与修复查三个仓库；修复另查 GitHub 登录与推送／部署权限。
2. **能做的直接做**：`prepare.py fix` 补齐默认配置（已有值不动，原文件备份），安装缺少的 tutti-ops，用 Homebrew 安装 gh，运行 `multica.py sync --prune` 把三个技能同步到 Multica workspace、分配给对应 Agent 并写入交接指令。
3. **一步步引导**：需要你本人做的（Multica 登录与建 Agent、`gh auth login`、管理端创建 Token、Chrome 点允许、找管理员要权限），一次一项给出步骤和可复制的命令，你回复「已完成」后 Agent 复查。
4. **收尾**：汇总已就绪／等你／等管理员；告诉你各场景怎么用。

插件更新后再同步一次技能：`python3 skills/bug-setup/scripts/multica.py sync --prune`（`status` 只读查看是否一致），见 [Multica 接入](skills/bug-setup/references/multica.md)。

默认配置（Multica profile／项目／Agent 名称、三个仓库、修复分支与泳道命名、PPE 部署、tutti-ops 管理端、本机 Computer 日志路径等）都已内置，见 [Setup Skill](skills/bug-setup/SKILL.md#默认配置)。数据目录默认 `~/.local/share/bug-workbench`（可用 `BUG_WORKBENCH_DATA` 覆盖），配置与运行记录都在这里，插件更新不影响。单项工具命令（`workbench.py doctor`、`setup-tutti-ops`、`configure-tutti-token`）仍可直接使用，见 [准备与授权教程](skills/bug-setup/references/setup-user-guide.md)。

## QA 提 Bug（`bug-investigate`）

自己不做根因分析，把现场带全后交给分析 Agent。流程见 [SKILL.md](skills/bug-investigate/SKILL.md)：

1. 接收上报（分配来的 issue 或对话），判断所属端、优先级、业务模块。
2. 沿用分配来的 issue，或在 Bug 项目里新建 issue（QA 的截图作为 issue 附件）。
3. Web 日志：本机 Chrome WebMCP 读页面日志（`merge_web_logs.py` 合并），不可用时用 QA 导出的诊断包；并行跑 Computer 召回（`collect_computer.py`，后台）；`web_requests.py` 列出失败请求及其 request id（`x-zk-request-id`），连同 Computer 日志里失败出站请求的 request id 写进排查线索。提 Bug 不查服务端日志、不依赖 AWS。
4. 现场齐了以后 `issue update` 改标题、写 Bug 表现、定优先级，`排查线索.txt` 和全部日志在一条「现场材料」评论里作为附件发出；回读确认。
5. `multica issue assign` 分配给分析 Agent，交出就不管；缺的现场之后发「现场补充」评论。最后上传本次会话。

## 根因分析（`bug-analyze`）

流程见 [SKILL.md](skills/bug-analyze/SKILL.md)：读 issue、评论和现场附件 → 把仓库更新到最新 main（数据目录的固定检出，只读）→ 按 [分析要求与回复格式](skills/bug-analyze/references/analysis.md) 找根因、弄清模块设计后给出根本／兼容方案、修复前后 Mermaid 流程图和验收要点 → 回复在 issue 里，状态 `in_review`。RD 在评论里追问时在同一 issue 里补充；不改代码，不自动交给修复。

## 修复与部署（`bug-execute`）

RD 认可方案后把 issue 分配给修复 Agent（或在本机 Codex 里说「修复这个 issue <编号>」），流程见 [SKILL.md](skills/bug-execute/SKILL.md) 与 [PPE 部署](skills/bug-execute/references/deploy.md)：

1. 读 issue、分析评论和 RD 的评审意见；分配本身即认可推荐方案，评论里另有指定时以评论为准；没有可用的方案就置为 `blocked` 说明缺什么。
2. 从最新 main 切 `codex/bug-<issue 编号小写>`（重试时接着原分支）→ 修复、测试 → 推送、提 PR 到 main。
3. 部署 PPE：先 tutti-server `deploy-lane`（泳道 `ppe-bug-<同样>`，关闭连接器授权），涉及 ws 时 tsh-websocket `deploy-lane`（同一泳道；新泳道需人工先建 ws 基础设施），再 tutti `platform-web-preview`（指向该泳道），涉及 Computer 时在分支上发 `Computer Canary`。
4. 用本机 Chrome（chrome-devtools MCP）打开预览链接，按验收要点自验证，涉及 UI 的每条用例截图。
5. 把一句话原因、PR、体验链接（前端预览，只改 Computer 时为 canary 发布页）、验证结果回复到 issue，验证截图作为评论附件；状态 `in_review`，失败 `blocked` 并写清卡在哪一步。
6. 泳道不自动销毁，需要时让 agent 用 `deploy.py destroy-lane` 销毁。

## 已提供的能力

- 四个可发现的 Skills：bug-investigate（QA 提 Bug）、bug-analyze（根因分析）、bug-execute（修复与部署）和 bug-setup（环境准备），Bug 记录在 Multica issue。
- `multica.py`：查看并同步 Multica workspace 的技能、Agent 技能分配与交接指令。
- 幂等初始化、环境检查、私有目录下的固定版本 npm CLI 安装。
- setup 复用已有 tutti-ops，缺少时按 `npm install -g @tutti-os/tutti-ops-cli` 全局安装，记录实际版本和入口；根据已安装命令的帮助与 schema 读取 Computer。
- 从实际配置生成便携 MCP 配置与旧版 Codex 兼容配置。

tutti-ops 使用用户指定的全局 npm 安装方式，要求 Node.js >=20 和 npm，详见 [tutti-ops 安装与认证](skills/bug-setup/references/tutti-ops-computer-logs.md)。其他 CLI 先填写可信 npm 包名与精确版本，再显式调用 `install-cli`；通用私有 npm 安装器不运行包的安装脚本，其他原生工具按实际安装方法适配。

插件不自带 MCP server（chrome-devtools 除外）。setup 不安装、不登录 AWS。其他 MCP 填写真实服务后使用 `configure-mcp --config CONFIG --output-dir PLUGIN_SOURCE` 生成配置，再通过安装流程更新插件。配置生成不代表服务已经部署、登录或连接成功。

Web 日志由 QA 在出问题的浏览器里自行导出：Tutti「设置 → 诊断 → 浏览器日志」选择覆盖故障时间的范围，点「导出日志」，得到 `tutti-web-diagnostics-<时间>.zip`（`manifest.json`、`errors.jsonl`、`logs.jsonl`，已脱敏）。Agent 把这个包原样作为 issue 评论附件上传，再解包阅读；QA 没附带时，排查到需要时连同其他问题一起请 QA 导出。详见 [Web 日志](skills/bug-investigate/references/web-logs.md)。

远端 Computer 日志通过 [tutti-ops CLI](skills/bug-investigate/references/tutti-ops-computer-logs.md) 定位 Computer、复用或创建召回、查询任务和生成链接，再下载、校验并读取日志包。setup 准备 CLI，使用前从 [admin.tutti.sh](https://admin.tutti.sh) 管理端获取 Token，通过 `configure-tutti-token` 隐藏输入，直接验证并保存到 CLI 本机配置，再核对实际环境与权限；当前 npm 包的原子操作已通过帮助、schema 和零网络预览验证，组合采集命令仅在实际发现后使用。

## 当前接入范围

QA 提 Bug 在 Multica 登记 issue。Web 日志使用 QA 导出的诊断包，见 [Web 日志](skills/bug-investigate/references/web-logs.md)。本地 computer 日志读取用户指定的明确文件路径；远端 computer 固定复用 Tutti 的日志召回流程，可使用 tutti-ops CLI 或实际 MCP 执行，见 [Computer 日志获取](skills/bug-investigate/references/computer-logs.md)。当前 Mac 已保存核实的三个本地主日志及 Codex 临时诊断路径，并记录轮转日志、VM 崩溃报告与导出漏收注意事项；其他机器需确认实际路径。本机 tutti-ops 已安装并完成离线能力核对，远端认证与真实日志采集尚待验证；其他使用者的宿主能力、远端环境／权限及验证地址仍需分别核对。Skills 可复用当前 Codex 会话的本地工具与已连接 MCP；当前包没有自带 MCP server 或常驻调度服务。共享此包携带仓库地址，不授予收件人访问权限，也不携带本机检出路径或凭证。

本地执行仍可能把选取的代码、日志片段和工具输出提交给模型。共享源码和分发包不包含真实业务数据或凭证。

提 Bug 不拉服务端日志：Web 与 Computer 日志里的请求都带网关 request id，记进排查线索，RD 排查时再按 id 查 tutti-server 日志。

## 验证插件源码

```sh
python3 PLUGIN_SOURCE/scripts/validate_plugin.py
for skill in skills/bug-investigate skills/bug-setup skills/bug-execute; do  # bug-analyze 没有脚本
  python3 -m unittest discover -s PLUGIN_SOURCE/$skill/tests -t PLUGIN_SOURCE/$skill/tests
done
```

打包时包括根部 `plugin.json`、`mcp.json`、`skills/` 和隐藏兼容文件。排除业务数据、凭证、工具安装目录与缓存。
