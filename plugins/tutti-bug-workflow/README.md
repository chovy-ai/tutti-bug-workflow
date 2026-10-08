# tutti-bug-workflow

版本：0.1.36。运行方式：Codex 本地会话。三个业务场景通过同一份 Bug 档案交接，公共初始化 Skill 准备配置与依赖。

| 入口 | 工作内容 |
|---|---|
| `$tutti-bug-workflow:bug-investigate` | 上报后自行分析代码与日志，再反馈结论或必要的现场追问 |
| `$tutti-bug-workflow:bug-solution` | 与 RD 协商方案，提供根本方案、兼容方案和设计图 |
| `$tutti-bug-workflow:bug-execute` | 执行批准方案，在指定环境验证并记录证据 |
| `$tutti-bug-workflow:bug-setup` | 按场景准备工具，主动补齐认证与权限并复查接入 |

## 首次使用

安装说明见分发目录根部的 README。安装后可在 Codex 中输入：

> 使用 $tutti-bug-workflow:bug-setup，先列出每步所需条件、已有值、待决策的获取方式和验证标准，这轮只梳理。

也可以指定“只准备 QA 分析／RD 方案／修复验证工具”。[场景工具 Setup](references/tool-setup.md) 列出公共工具、条件工具和准备顺序；只读清单命令 `scripts/tool_setup.py --scene solution` 支持按场景查看，使用 `--include TOOL_ID` 启用条件项。工具准备沿用现有安装入口，清单脚本不执行安装或认证。

使用者可按 [准备与授权教程](references/setup-user-guide.md) 操作：Agent 先完成所有选中工具的安装或复用及可执行检查，安装阶段结束后立即进入授权；需要本人登录或补充权限时给出实际入口与步骤，完成后复查并继续。

完整的逐步准备清单写在 [Setup Skill](skills/bug-setup/SKILL.md)。梳理模式只检查已有信息；确定接入方式后，再执行初始化：

> 使用 $tutti-bug-workflow:bug-setup 初始化 Bug 工作台，复用或安装 tutti-ops 与 AWS CLI，检查日志入口，完成全部工具安装后立即进入授权，主动检查并补齐权限，必要的本人授权完成后继续验证。

初始化脚本只依赖 Python 3.10+ 标准库。将下面的 `PLUGIN_SOURCE` 替换为插件源码目录：

```sh
python3 PLUGIN_SOURCE/scripts/workbench.py init
python3 PLUGIN_SOURCE/scripts/workbench.py doctor
python3 PLUGIN_SOURCE/scripts/workbench.py setup-tutti-ops --install
python3 PLUGIN_SOURCE/scripts/workbench.py setup-aws-cli --install
```

上述安装完成后立即进入授权。tutti-ops 使用 Token：运行 `python3 PLUGIN_SOURCE/scripts/workbench.py configure-tutti-token`，隐藏输入后校验并保存，后续自动复用；飞书和 AWS 沿用各自认证流程。

默认数据目录为 `~/.local/share/bug-workbench`，可用 `--data-dir` 或环境变量 `BUG_WORKBENCH_DATA` 覆盖。配置、Bug 档案与安装的工具保存在数据目录，独立于插件源码和安装缓存。

数据目录的 `config.json` 已默认绑定指定的飞书 Bug 表、真实字段、三个视图，以及 tutti 和 tutti-server 的远端 main。补充 Web/目标 computer 的日志来源与验证环境后开始对应场景；已有配置不会被初始化覆盖。每个场景读取同一份配置，实际参数见 [配置说明](references/configuration.md)。

## 固定的飞书工作台

使用同一张「Bug 列表」的「流程状态」单选字段区分三个阶段：

| 状态与视图 | 工作内容 |
|---|---|
| [bug单](https://ccn53rwonxso.feishu.cn/base/RYLPb6dGma0e6Wsb8v6c4HhBntg?table=tblceDIio9QmR8ou&view=vewOTNRVFB) | QA 提交、补充上下文、根因分析；空状态的旧记录也显示在这里 |
| [待 review 方案](https://ccn53rwonxso.feishu.cn/base/RYLPb6dGma0e6Wsb8v6c4HhBntg?table=tblceDIio9QmR8ou&view=vewVkuJ7Ue) | 方案已回填，RD 讨论和批准；修复执行及未通过的验证继续留在这里 |
| [已自动修复并验证，待验收](https://ccn53rwonxso.feishu.cn/base/RYLPb6dGma0e6Wsb8v6c4HhBntg?table=tblceDIio9QmR8ou&view=vewaFbwWDG) | 已核对修复版本、完成验证并回填证据，等待 QA/RD 人工验收 |

报告按 [独立字段](references/report-fields.md) 回填：结论、根因、排查验证、基线、代码路径、方案、验收、修复后验证、沟通和待核实项分别保存。根因字段只写简洁因果链，完整报告留在本地档案；旧记录按明确授权迁移。状态切换规则见 [工作流与交接](references/workflow.md)。视图配置已经生效；自动触发需另接后续流程服务。

「bug单」场景每次固定两个最新远端 main 的 SHA，在隔离工作树中按 [业务逻辑、日志与复现路径](references/root-cause-analysis.md) 逐节点推演原现象。解释中间报错后仍须验证后续恢复与最终状态；日志与逻辑不闭合时沿缺失节点补 Web、Server、Computer 或必要观测。给出主复现路径后再检查其他入口与时序，分别注明推演和已执行结果。回填用两到四句说明触发、首个错误状态、传播与最终现象；资料不足时继续可自行完成的验证，只有必要的原现场信息才向 QA 追问。

日志附件按 [集中规则](references/registration-logs.md#日志文件与附件数量) 提交：已有单个／多个日志文件或诊断包读取核对后原样上传；逐条取得的内容按时间合并为 `web-logs.log`、`computer-logs.log`、`server-logs.log`，每来源一份，不为凑齐来源制造文件。查询 JSON、清单、工具发现、报告和测试输出默认保存在本地，字段记录必要结论，避免逐轮增加过程附件。

三个 Bug 场景每轮结束前按 [当前 provider 的会话上传](references/session-upload.md) 将本会话原生 JSONL 快照上传到 Tutti 管理端，供后续优化；等待 QA/RD 和受阻也保留本轮上下文。核对当前宿主与 session 身份，保存确认回执、Bug/运行关联及失败恢复条件；会话不追加为飞书现场日志附件。tutti-ops 已核对的发布版本为 0.1.7，旧版需检查并补齐实际 session 命令与上传权限。

用户提出 Bug 时，先按 [登记日志规则](references/registration-logs.md) 保存问题和可获取的相关 Web、desktopd 日志，再默认执行本轮代码与证据分析。明确仅登记或仅补附件、不分析时按其范围执行。日志与工具缺口保存在技术记录中，继续可进行的独立分析。 Web 与 Computer 日志分别按具体证据缺口判断是否需要；先复用已有材料，只采集相关来源。原现场关联、Web DOM 状态及 Computer 执行边界分别验证，已有证据充分时无需追加。

QA 提示词按六步执行，并为每步定义完成条件，见 [QA Bug 上报与根因分析](skills/bug-investigate/SKILL.md)。本轮可自行执行的关键分析完成后，按 [QA 反馈、追问与恢复](references/qa-dialogue.md) 反馈事实与判断；追问仅针对能推进验证的现场观察。接入、命令、内部 ID 和认证细节由维护侧处理，QA 通过产品表现、操作顺序或实际设备名称补充。

涉及 Computer 时按 [Computer 定位与 QA 询问](references/computer-target.md) 判断日志用途，优先关联故障请求中的 ID；缺少时通过页面的 `list_my_computers`、`list_rooms`、`list_room_agents` 查询真实候选，必要时请 QA 确认设备、房间／Agent 和发生时间。当前选中的设备不能代替故障时的目标，目录访问与远端日志权限分别核对。

代码固定缓存到数据目录的 `repositories/tutti.git`、`repositories/tutti-server.git`。首次初始化可复用现有仓库的已提交对象，后续只获取 main 的增量；每条 Bug 使用共享对象的独立 worktree。详见 [代码缓存](references/repository-cache.md)。

创建一份档案：

```sh
python3 PLUGIN_SOURCE/scripts/workbench.py new-bug --bug-id BUG-001
```

然后分别使用三个场景。可以在独立会话中提供同一个 Bug ID 和数据目录；插件本身不会自动创建三个会话。

## 已提供的能力

- 四个可发现的 Skills；其中三个是业务场景。
- 共享工作流规则，以及根因、方案、验收与验证模板。
- 幂等初始化、环境检查、私有目录下的固定版本 npm CLI 安装。
- setup 复用已有 tutti-ops，缺少时按 `npm install -g @tutti-os/tutti-ops-cli` 全局安装，记录实际版本和入口；根据已安装命令的帮助与 schema 读取 Computer。
- setup 准备 AWS CLI v2，复用已有安装，缺少时通过 AWS 官方安装器补齐；完整 Setup 接续身份检查和缺口处理，完成必要的本人操作后复查实际访问。
- 固定 bare 代码缓存、增量同步、更新锁及每轮 main 的持久化快照。
- 从实际配置生成便携 MCP 配置与旧版 Codex 兼容配置。
- 执行前检查报告版本、仓库版本、批准引用和报告内容摘要的一致性。

AWS CLI 使用专用官方安装器，新安装固定版本，核对安装脚本摘要和最终版本，详见 [AWS CLI 安装与日志读取](references/aws-cli.md)。tutti-ops 使用用户指定的全局 npm 安装方式，要求 Node.js >=20 和 npm，详见 [tutti-ops 准备与使用](references/tutti-ops-computer-logs.md)。其他 CLI 先填写可信 npm 包名与精确版本，再显式调用 `install-cli`；通用私有 npm 安装器不运行包的安装脚本，其他原生工具按实际安装方法适配。

插件内的 MCP 配置目前为空；AWS 默认使用 CLI。确认 CLI 可用后，仅清理由旧插件创建且未被改动的 AWS MCP，保留其他连接。AWS MCP 仅在用户明确要求恢复时按 [兼容接入](references/aws-mcp.md) 配置。其他 MCP 填写真实服务后使用 `configure-mcp --config CONFIG --output-dir PLUGIN_SOURCE` 生成配置，再通过安装流程更新插件。配置生成不代表服务已经部署、登录或连接成功。

WebMCP 先检查已授权宿主浏览器的真实能力；配置为空时仍可按 [宿主发现与 CDP 路径](references/web-logs.md#宿主浏览器能力发现与-cdp-路径) 验证。分析 Skill 明确页面匹配、按假设查询、逐次覆盖与截断判断、DOM／Computer 因果证据及保存规则。

判断需要 Web 日志后，Agent 本轮自动结合用户截图匹配页面，固定提出本次问题的时间，读取此前 10 分钟目标页面／Account 的全部保留级别记录。WebMCP 逐条返回的内容归并为单个 `web-logs.log`，已有诊断文件／包保留原样，上传到同一条 Bug 后回读；必要时读取可见 DOM。无需 QA 再次询问或重复确认已有授权。采集延迟时扩展查询后按固定窗口核对，截断或历史缺口如实记录并补采；只有实际权限、目标或原现场材料缺口才提出必要问题。详见 [固定流程](references/web-logs.md#固定流程提问前-10-分钟--单个-log-附件)。

WebMCP 首次启用时，按 [带截图的启用与授权引导](references/web-logs.md#发给用户的启用与授权引导) 找到 **WebMCP for testing** 并设为 **Enabled**。同一张配置截图已加入插件介绍图片。

远端 Computer 日志通过 [tutti-ops CLI](references/tutti-ops-computer-logs.md) 定位 Computer、复用或创建召回、查询任务和生成链接，再下载、校验并读取日志包。setup 准备 CLI，使用前从 [admin.tutti.sh](https://admin.tutti.sh) 管理端获取 Token，通过 `configure-tutti-token` 隐藏输入，直接验证并保存到 CLI 本机配置，再核对实际环境与权限；当前 npm 包的原子操作已通过帮助、schema 和零网络预览验证，组合采集命令仅在实际发现后使用。

## 当前接入范围

飞书表格、字段和三个视图已绑定，并在本机通过 user 身份读取验证。两仓库 URL 与 main 分支已配置。Web 日志复用 [PR #2341](https://github.com/tutti-lab/tutti/pull/2341) 的原生 `get_web_logs` 与截图页面识别，需已授权浏览器桥访问目标标签页；已提供识别失败时的启用/授权引导及历史诊断导出方案，见 [Web 日志获取](references/web-logs.md)。本地 computer 日志读取用户指定的明确文件路径；远端 computer 固定复用 Tutti 的日志召回流程，可使用 tutti-ops CLI 或实际 MCP 执行，见 [Computer 日志获取](references/computer-logs.md)。当前 Mac 已保存核实的三个本地主日志及 Codex 临时诊断路径，并记录轮转日志、VM 崩溃报告与导出漏收注意事项；其他机器需确认实际路径。本机 tutti-ops 已安装并完成离线能力核对，远端认证与真实日志采集尚待验证；本机已通过宿主 Chrome CDP 发现并执行原生 WebMCP，取得匹配页面的日志与现场 DOM；其他使用者的宿主能力、远端环境／权限及验证地址仍需分别核对。Skills 可复用当前 Codex 会话的本地工具与已连接 MCP；当前包没有自带飞书连接器、浏览器服务器或常驻调度服务。共享此包携带表格和仓库地址，不授予收件人访问权限，也不携带本机检出路径或凭证。

飞书事件触发、重试、事件去重、跨设备调度与可信 RD 审批属于后续流程服务，契约见 [工作流与交接](references/workflow.md)。本版 `check-execution` 只检查本地档案一致性；RD 身份与批准来源仍需通过实际飞书记录或直接用户消息核实。

本地执行仍可能把选取的代码、日志片段和工具输出提交给模型。共享源码和分发包不包含真实业务档案或凭证。

服务端日志判断必需或建议补／可辅助后，在本轮立即调用实际Tutti CLI或已确认AWS来源的AWS CLI，先保存易失证据，追加上传同一条Bug并回读；不会停在建议或等待QA追问。成功访问记录不能用HTTP失败归因空结果代替。详见 [服务端日志](references/server-logs.md)。

## 验证插件源码

```sh
python3 PLUGIN_SOURCE/scripts/validate_plugin.py
python3 -m unittest discover -s PLUGIN_SOURCE/tests -v
```

打包时包括根部 `plugin.json`、`mcp.json`、`skills/` 和隐藏兼容文件。排除业务数据、凭证、工具安装目录与缓存。
