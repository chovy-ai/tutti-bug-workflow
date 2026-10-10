# tutti-bug-workflow

版本：0.1.38。运行方式：Codex 本地会话。三个业务场景通过同一份 Bug 档案交接，公共初始化 Skill 准备配置与依赖。

| 入口 | 工作内容 |
|---|---|
| `$tutti-bug-workflow:bug-investigate` | 上报后自行分析代码与日志，再反馈结论或必要的现场追问 |
| `$tutti-bug-workflow:bug-solution` | 与 RD 协商方案，提供根本方案、兼容方案和设计图 |
| `$tutti-bug-workflow:bug-execute` | 执行批准方案，在指定环境验证并记录证据 |
| `$tutti-bug-workflow:bug-setup` | 按场景准备工具，主动补齐认证与权限并复查接入 |

## 首次使用

安装说明见分发目录根部的 README。安装后可在 Codex 中输入：

> 使用 $tutti-bug-workflow:bug-setup，先列出每步所需条件、已有值、待决策的获取方式和验证标准，这轮只梳理。

也可以指定“只准备 QA 分析／RD 方案／修复验证工具”。[场景工具 Setup](skills/bug-setup/references/tool-setup.md) 列出公共工具、条件工具和准备顺序；只读清单命令 `skills/bug-setup/scripts/tool_setup.py --scene solution` 支持按场景查看，使用 `--include TOOL_ID` 启用条件项。工具准备沿用现有安装入口，清单脚本不执行安装或认证。

使用者可按 [准备与授权教程](skills/bug-setup/references/setup-user-guide.md) 操作：Agent 先完成所有选中工具的安装或复用及可执行检查，安装阶段结束后立即进入授权；需要本人登录或补充权限时给出实际入口与步骤，完成后复查并继续。

完整的逐步准备清单写在 [Setup Skill](skills/bug-setup/SKILL.md)。梳理模式只检查已有信息；确定接入方式后，再执行初始化：

> 使用 $tutti-bug-workflow:bug-setup 初始化 Bug 工作台，复用或安装 tutti-ops 与 AWS CLI，检查日志入口，完成全部工具安装后立即进入授权，主动检查并补齐权限，必要的本人授权完成后继续验证。

初始化脚本只依赖 Python 3.10+ 标准库。将下面的 `PLUGIN_SOURCE` 替换为插件源码目录：

```sh
python3 PLUGIN_SOURCE/skills/bug-setup/scripts/workbench.py init
python3 PLUGIN_SOURCE/skills/bug-setup/scripts/workbench.py doctor
python3 PLUGIN_SOURCE/skills/bug-setup/scripts/workbench.py setup-tutti-ops --install
python3 PLUGIN_SOURCE/skills/bug-setup/scripts/workbench.py setup-aws-cli --install
```

上述安装完成后立即进入授权。tutti-ops 使用 Token：运行 `python3 PLUGIN_SOURCE/skills/bug-setup/scripts/workbench.py configure-tutti-token`，隐藏输入后校验并保存，后续自动复用；飞书和 AWS 沿用各自认证流程。

默认数据目录为 `~/.local/share/bug-workbench`，可用 `--data-dir` 或环境变量 `BUG_WORKBENCH_DATA` 覆盖。配置、Bug 档案与安装的工具保存在数据目录，独立于插件源码和安装缓存。

数据目录的 `config.json` 已默认绑定指定的飞书 Bug 表、真实字段、三个视图，以及 tutti 和 tutti-server 的远端 main。补充 Web/目标 computer 的日志来源与验证环境后开始对应场景；已有配置不会被初始化覆盖。每个场景读取同一份配置，实际参数见 [配置说明](skills/bug-setup/references/configuration.md)。

## 固定的飞书工作台

使用同一张「Bug 列表」的「流程状态」单选字段区分三个阶段：

| 状态与视图 | 工作内容 |
|---|---|
| [bug单](https://ccn53rwonxso.feishu.cn/base/RYLPb6dGma0e6Wsb8v6c4HhBntg?table=tblceDIio9QmR8ou&view=vewOTNRVFB) | QA 提交、补充上下文、根因分析；空状态的旧记录也显示在这里 |
| [待 review 方案](https://ccn53rwonxso.feishu.cn/base/RYLPb6dGma0e6Wsb8v6c4HhBntg?table=tblceDIio9QmR8ou&view=vewVkuJ7Ue) | 方案已回填，RD 讨论和批准；修复执行及未通过的验证继续留在这里 |
| [已自动修复并验证，待验收](https://ccn53rwonxso.feishu.cn/base/RYLPb6dGma0e6Wsb8v6c4HhBntg?table=tblceDIio9QmR8ou&view=vewaFbwWDG) | 已核对修复版本、完成验证并回填证据，等待 QA/RD 人工验收 |

报告按 [独立字段](skills/bug-investigate/references/report-fields.md) 回填：结论、根因、排查验证、基线、代码路径、方案、验收、修复后验证、沟通和待核实项分别保存。根因字段只写简洁因果链；旧记录按明确授权迁移。状态切换规则见 [工作流与交接](skills/bug-setup/references/workflow.md)。视图配置已经生效；自动触发需另接后续流程服务。

### QA 提 Bug（`bug-investigate`）

无状态：流程状态只在 Agent 会话上下文中，飞书记录是唯一事实来源；日志、召回包、代码工作区都是会话临时文件。流程见 [SKILL.md](skills/bug-investigate/SKILL.md)：

1. 接收 QA 上报，`scripts/feishu.py create` 建单或找回同名记录。
2. 上传 QA 导出的 Web 诊断包（Tutti「设置 → 诊断 → 导出日志」，原样上传），采集 Computer 日志（从诊断包 `manifest.computers[]` 或 QA 提供的设备定位 → `scripts/collect_computer.py` 本机读取或远端召回）；`feishu.py attach` 上传，`scripts/check_collection.py` 汇报现状。采不到就记原因继续。
3. 读两个最新 main 的代码，按 [业务逻辑、日志与复现路径](skills/bug-investigate/references/root-cause-analysis.md) 推演因果链；Server 日志由 Agent 按 [服务端日志](skills/bug-investigate/references/server-logs.md) 判断是否查询。
4. 根因确认后 `feishu.py write` 分字段回填；只有自己无法解决的卡点（缺 Web 诊断包、需选设备等）才一次性问 QA，并说明获取方式。
5. 排查结束后上传本次会话一次，见 [会话上传](skills/bug-investigate/references/session-upload.md)。
代码固定缓存到数据目录的 `repositories/tutti.git`、`repositories/tutti-server.git`。首次初始化可复用现有仓库的已提交对象，后续只获取 main 的增量；每条 Bug 使用共享对象的独立 worktree。详见 [代码缓存](skills/bug-investigate/references/repository-cache.md)。

创建一份档案：

```sh
python3 PLUGIN_SOURCE/skills/bug-solution/scripts/dossier.py new-bug --bug-id BUG-001
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

AWS CLI 使用专用官方安装器，新安装固定版本，核对安装脚本摘要和最终版本，详见 [AWS CLI 安装](skills/bug-setup/references/aws-cli.md)。tutti-ops 使用用户指定的全局 npm 安装方式，要求 Node.js >=20 和 npm，详见 [tutti-ops 安装与认证](skills/bug-setup/references/tutti-ops-computer-logs.md)。其他 CLI 先填写可信 npm 包名与精确版本，再显式调用 `install-cli`；通用私有 npm 安装器不运行包的安装脚本，其他原生工具按实际安装方法适配。

插件不自带 MCP server；AWS 默认使用 CLI。确认 CLI 可用后，仅清理由旧插件创建且未被改动的 AWS MCP，保留其他连接。AWS MCP 仅在用户明确要求恢复时按 [兼容接入](skills/bug-setup/references/aws-mcp.md) 配置。其他 MCP 填写真实服务后使用 `configure-mcp --config CONFIG --output-dir PLUGIN_SOURCE` 生成配置，再通过安装流程更新插件。配置生成不代表服务已经部署、登录或连接成功。

Web 日志由 QA 在出问题的浏览器里自行导出：Tutti「设置 → 诊断 → 浏览器日志」选择覆盖故障时间的范围，点「导出日志」，得到 `tutti-web-diagnostics-<时间>.zip`（`manifest.json`、`errors.jsonl`、`logs.jsonl`，已脱敏）。Agent 把这个包原样上传到 Bug 单，再解包阅读；QA 没附带时，排查到需要时连同其他问题一起请 QA 导出。详见 [Web 日志](skills/bug-investigate/references/web-logs.md)。

远端 Computer 日志通过 [tutti-ops CLI](skills/bug-investigate/references/tutti-ops-computer-logs.md) 定位 Computer、复用或创建召回、查询任务和生成链接，再下载、校验并读取日志包。setup 准备 CLI，使用前从 [admin.tutti.sh](https://admin.tutti.sh) 管理端获取 Token，通过 `configure-tutti-token` 隐藏输入，直接验证并保存到 CLI 本机配置，再核对实际环境与权限；当前 npm 包的原子操作已通过帮助、schema 和零网络预览验证，组合采集命令仅在实际发现后使用。

## 当前接入范围

飞书表格、字段和三个视图已绑定，并在本机通过 user 身份读取验证。两仓库 URL 与 main 分支已配置。Web 日志使用 QA 导出的诊断包，见 [Web 日志](skills/bug-investigate/references/web-logs.md)。本地 computer 日志读取用户指定的明确文件路径；远端 computer 固定复用 Tutti 的日志召回流程，可使用 tutti-ops CLI 或实际 MCP 执行，见 [Computer 日志获取](skills/bug-investigate/references/computer-logs.md)。当前 Mac 已保存核实的三个本地主日志及 Codex 临时诊断路径，并记录轮转日志、VM 崩溃报告与导出漏收注意事项；其他机器需确认实际路径。本机 tutti-ops 已安装并完成离线能力核对，远端认证与真实日志采集尚待验证；其他使用者的宿主能力、远端环境／权限及验证地址仍需分别核对。Skills 可复用当前 Codex 会话的本地工具与已连接 MCP；当前包没有自带 MCP server、飞书连接器或常驻调度服务。共享此包携带表格和仓库地址，不授予收件人访问权限，也不携带本机检出路径或凭证。

飞书事件触发、重试、事件去重、跨设备调度与可信 RD 审批属于后续流程服务，契约见 [工作流与交接](skills/bug-setup/references/workflow.md)。本版 `check-execution` 只检查本地档案一致性；RD 身份与批准来源仍需通过实际飞书记录或直接用户消息核实。

本地执行仍可能把选取的代码、日志片段和工具输出提交给模型。共享源码和分发包不包含真实业务档案或凭证。

服务端日志判断必需或建议补／可辅助后，在本轮立即调用实际Tutti CLI或已确认AWS来源的AWS CLI，先保存易失证据，追加上传同一条Bug并回读；不会停在建议或等待QA追问。成功访问记录不能用HTTP失败归因空结果代替。详见 [服务端日志](skills/bug-investigate/references/server-logs.md)。

## 验证插件源码

```sh
python3 PLUGIN_SOURCE/scripts/validate_plugin.py
for skill in bug-investigate bug-setup bug-solution bug-execute; do
  python3 -m unittest discover -s PLUGIN_SOURCE/skills/$skill/tests -t PLUGIN_SOURCE/skills/$skill/tests
done
```

打包时包括根部 `plugin.json`、`mcp.json`、`skills/` 和隐藏兼容文件。排除业务数据、凭证、工具安装目录与缓存。
