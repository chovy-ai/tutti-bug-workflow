# 按场景组织工具 Setup

用于选择工具、规划安装或复用、记录授权与验证缺口。场景及工具选择的可执行目录在 `config/tool-profiles.json`；`scripts/tool_setup.py` 读取已有配置并输出准备清单，不安装、不认证、不联网，也不初始化数据目录。

## 场景边界

| 场景 | 每次需要的工具 | 按实际任务启用 |
|---|---|---|
| `investigate`：QA 上报与根因分析 | 本地文件/搜索/终端/图片查看、飞书记录/附件、Git 与代码缓存 | Web 日志、截图解码、Computer 目录、本地或远端 Computer 日志、Server/Tutti CLI 与 AWS 日志；必要的测试或浏览器复现 |
| `solution`：RD 方案协商 | 共享的本地/飞书/Git 能力，以及 Mermaid 图源码生成 | 导出图片/PDF 时的实际渲染器；新日志或复现需求交回分析场景 |
| `execute`：修复与验证 | 共享的本地/飞书/Git 能力、批准核对、项目测试/类型检查/lint、浏览器验收与证据保存 | GitHub/PR 交付工具、部署工具，以及排查或验证需要的日志来源 |

QA 每轮更新两个最新 main，RD 与执行读取交接的固定基线；工具准备不擅自更新已批准的修复版本。RD 所需图可以先交付 Mermaid 源码，专用图服务或图片渲染工具属于条件项。

## 工具目录与准备方式

| 工具 ID | 工具 / 提供方式 | 安装或复用条件 | 授权与真实验证条件 |
|---|---|---|---|
| `local-workspace` | Codex 本地文件、搜索、终端与图片查看 | Python 3.10+；实际宿主能力；可读源码/附件及可写证据目录 | 分别核对文件访问与执行范围；跨机器资源不能由本地路径代替 |
| `feishu` | 默认 lark-cli，或已提供的飞书宿主工具/MCP | 复用入口；缺少 CLI 时先核实官方安装方式，当前无默认自动安装器 | 指定身份、记录和附件读写权限；分别验证读取与回填 |
| `code` | Git、bare 缓存、worktree | 复用 Git；两仓库 URL/main、缓存目录与空间 | GitHub 网络与两仓库读取权限；执行交付另需写权限 |
| `diagrams` | Mermaid 源码生成；条件性渲染器 | 文本图无需新装 CLI/MCP；输出图片/PDF 时准备实际渲染入口 | 源码生成不代表图片已渲染，按交付格式检查 |
| `approval` | 可信消息读取 + 本地 `check-execution` | 复用飞书/直接用户消息来源、Python 检查脚本 | 每条 Bug 核对真实 RD 批准与方案版本；本地一致性不证明身份 |
| `project-checks` | 项目实际运行时、依赖与测试工具 | 读取对应 checkout 的 AGENTS.md、开发说明、锁文件和检查命令后准备 | 相关测试/类型检查/lint 实际通过；环境阻塞与测试失败分开记录 |
| `browser-validation` | Playwright、浏览器 MCP 或宿主浏览器工具 | 选一个实际入口，准备浏览器、环境 URL、证据输出和版本读取方法 | 登录态、测试数据及所需交互权限；执行验收用例并保存证据 |
| `web-logs` | 能转发原生 WebMCP 的浏览器桥 | 页面发现/工具发现/执行三个能力；桥为 MCP 时再注册服务 | 匹配现场账号和页面，成功调用 `get_web_logs`；QA 异机需要其侧授权入口 |
| `screenshot-decoder` | Tutti 仓库水印解码脚本 | Node 24+、按 checkout 要求的 pnpm/锁文件准备 sharp 及原生依赖 | 原始截图可读；区分依赖缺失、无水印与识别成功 |
| `computer-directory` | 页面目录；或 tutti-ops 管理目录 | 页面 `list_my_computers`/`list_rooms`/`list_room_agents`；选管理 CLI 时同时启用 `remote-computer` 的 CLI 准备 | 正确账号/环境的目录可见范围；本机身份另用状态命令或可信绑定证据 |
| `local-computer` | 明确路径的本地日志读取 | 复用文件工具；实际状态目录、临时目录与日志路径 | 本机身份匹配与文件读取权限；实际覆盖时间/轮转情况 |
| `remote-computer` | 默认 tutti-ops；实际远端 MCP 可替代 | `setup-tutti-ops --install`，缺少时执行 `npm install -g @tutti-os/tutti-ops-cli`；Node >=20/npm/全局目录写权限 | 默认 `https://admin.tutti.sh`、[管理端 Token 获取与本机配置](tutti-ops-computer-logs.md#环境与认证)、目录/召回/下载权限；下载后校验、解包并读取 |
| `server-logs` | 实际 Tutti CLI（当前默认 tutti-ops） | 发现命令/schema，按所需日志类别选择；必要时同时启用 `aws-logs` | 同条Bug的服务/环境/窗口、日志读取权限；必需或建议补后立即采集/上传，HTTP失败入口不代替成功请求 |
| `aws-logs` | AWS CLI v2 | `setup-aws-cli --install` 复用或官方安装；下载网络、用户安装目录与系统安装器依赖 | 确认日志在 AWS；目标账号/区域/日志组与读取权限，选中后主动检查并处理认证缺口 |
| `github-delivery` | gh 或实际 GitHub 宿主工具 | 选 gh 时准备其安装；复用已有 Git | 实际推送与 PR 权限；创建成功后附加到当前任务 |
| `deployment` | 项目既有部署/预览流程 | 真实工具、流水线或预览产出方式；不固定猜测某个部署 CLI | 任务授权、目标环境权限、部署结果和修复 SHA 一致 |

其他 CLI、浏览器桥、MCP、渲染器和部署工具的安装方法由所选提供方决定，尚未提供时列“待决策”。具体输入和完成标准仍按 [Setup 的逐步条件](../skills/bug-setup/SKILL.md) 执行。

## 工具 Setup 的顺序

1. **选择场景**：根据任务选 `investigate`、`solution` 或 `execute`；未指定时用 `all` 展示全目录。按问题实际链路选择日志来源；条件工具不会因为出现在目录中就自动安装。
2. **输出准备清单**：运行下面的只读命令。每个必需工具都选中，条件工具用 `--include` 启用。无配置时先用 Setup 梳理模式说明缺口；执行模式才初始化配置。
3. **安装与复用**：已授权进行工具准备时，对选中的工具执行已有准备入口。当前自动准备入口只有 tutti-ops 和 AWS CLI；其他工具列出已核实的方法或待决策提供方。保存入口、版本和安装结果，自定义入口先核对。先完成全部选中工具的安装和可执行检查；失败项处理或记录具体阻塞后，立即进入下一阶段。
4. **立即进入授权**：安装阶段结束后自动开始，无需再次询问是否授权。已确定的飞书、仓库、浏览器、Computer、AWS、验证环境分别按对应来源准备。复用有效认证；发现缺口时按 [主动补齐授权](setup-user-guide.md#主动补齐授权) 修复配置、发起登录并给出真实入口；本人完成后接续登录、复查目标访问。用户明确跳过时才延期；MCP 按实际选择接入。
5. **验证真实能力**：在授权范围内逐项核对。宿主工具、浏览器桥、图渲染、项目检查与远端权限需要实际发现/执行；清单脚本只检查 CLI 路径及已有配置形状，不运行工具或测试。
6. **交付场景结果**：列出选中工具、未启用的条件项、已安装/已配置/待授权/待验证/已验证状态和受影响能力。后续场景复用已有准备，只补新增工具。

脚本返回码 0 表示清单已生成，不表示工作流可执行；它明确输出 `authentication: not_checked`、`business_access: not_checked`。工具安装计划只是参数数组，脚本不会执行它。原有完整 Setup、`doctor` 和独立安装命令继续可用，`doctor` 的全局结果不替代场景清单。

Web 浏览器桥未配置时，先检查当前宿主的已授权浏览器能力，按 [WebMCP 宿主发现与 CDP 路径](web-logs.md#宿主浏览器能力发现与-cdp-路径) 验证能否发现及执行页面原生只读工具。配置检查失败与本轮真实调用成功可以同时成立，分别保存结果；不凭配置空值认定无法读取，也不为消除提示填写虚构工具名。

```sh
# RD 方案场景：检查公共工具和 Mermaid 源码能力
python3 PLUGIN_SOURCE/scripts/tool_setup.py --scene solution

# QA：按已确认链路选择 Web 与远端 Computer 日志
python3 PLUGIN_SOURCE/scripts/tool_setup.py --scene investigate --include web-logs --include computer-directory --include remote-computer

# 执行：公共/测试/浏览器能力，加上选定的 PR 与部署方式
python3 PLUGIN_SOURCE/scripts/tool_setup.py --scene execute --include github-delivery --include deployment

# 先展示全目录；条件工具保持未启用
python3 PLUGIN_SOURCE/scripts/tool_setup.py --scene all
```

将 `PLUGIN_SOURCE` 替换为实际插件目录。使用其他数据配置时追加 `--data-dir DATA_DIR` 或 `--config CONFIG`；生成的安装计划保留相同数据目录与配置入口。已有 QA 材料不足以判断日志来源时先分析代码和证据，工具接入问题保存在维护侧，QA 只回答必要的现场问题。
