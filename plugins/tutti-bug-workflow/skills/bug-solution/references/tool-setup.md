# 按场景组织工具 Setup

用于选择工具、规划安装或复用、记录授权与验证缺口。场景及工具选择的可执行目录在 `config/tool-profiles.json`；`scripts/tool_setup.py` 读取已有配置并输出准备清单，不安装、不认证、不联网，也不初始化数据目录。

工具的安装、认证与准备清单由 `$tutti-bug-workflow:bug-setup` 执行；本页只列出各场景需要哪些工具，供判断缺口。

## 场景边界

| 场景 | 每次需要的工具 | 按实际任务启用 |
|---|---|---|
| `investigate`：QA 上报与根因分析 | 本地文件/搜索/终端/图片查看、飞书记录/附件、Git 与代码缓存、提 Bug 结束后的 session 上传 | Web 日志、Computer 目录、本地或远端 Computer 日志、Server/Tutti CLI 与 AWS 日志；必要的测试或浏览器复现 |
| `solution`：RD 方案协商 | 共享的本地/飞书/Git 能力，以及 Mermaid 图源码生成 | 导出图片/PDF 时的实际渲染器；新日志或复现需求交回分析场景 |
| `execute`：修复与验证 | 共享的本地/飞书/Git 能力、批准核对、项目测试/类型检查/lint、浏览器验收与证据保存 | GitHub/PR 交付工具、部署工具，以及排查或验证需要的日志来源 |

QA 每轮更新两个最新 main，RD 与执行读取交接的固定基线；工具准备不擅自更新已批准的修复版本。RD 所需图可以先交付 Mermaid 源码，专用图服务或图片渲染工具属于条件项。

`investigate` 需准备 提 Bug 结束后的会话上传：核对 tutti-ops 实际 session 命令、当前宿主日志入口及管理端上传权限，确认提 Bug 结束后才执行。会话归档接入缺口单独记录，继续可进行的业务工作；`solution` 与 `execute` 不把该能力列为必需项。

## 工具目录与准备方式

| 工具 ID | 工具 / 提供方式 | 安装或复用条件 | 授权与真实验证条件 |
|---|---|---|---|
| `local-workspace` | Codex 本地文件、搜索、终端与图片查看 | Python 3.10+；实际宿主能力；可读源码/附件及可写证据目录 | 分别核对文件访问与执行范围；跨机器资源不能由本地路径代替 |
| `feishu` | 默认 lark-cli，或已提供的飞书宿主工具/MCP | 复用入口；缺少 CLI 时先核实官方安装方式，当前无默认自动安装器 | 指定身份、记录和附件读写权限；分别验证读取与回填 |
| `code` | Git、bare 缓存、worktree | 复用 Git；两仓库 URL/main、缓存目录与空间 | GitHub 网络与两仓库读取权限；执行交付另需写权限 |
| `session-upload` | tutti-ops Session JSONL 上传 | `setup-tutti-ops --install` 先复用；按 session 能力检查 核对命令，旧版缺能力时升级官方包；当前宿主提供会话定位/导出 | 管理端认证、diagnostics write、`session_logs.write`；核对当前 provider/session 身份，实际确认 uploaded 才表示上传完成 |
| `diagrams` | Mermaid 源码生成；条件性渲染器 | 文本图无需新装 CLI/MCP；输出图片/PDF 时准备实际渲染入口 | 源码生成不代表图片已渲染，按交付格式检查 |
| `approval` | 可信消息读取 + 本地 `check-execution` | 复用飞书/直接用户消息来源、Python 检查脚本 | 每条 Bug 核对真实 RD 批准与方案版本；本地一致性不证明身份 |
| `project-checks` | 项目实际运行时、依赖与测试工具 | 读取对应 checkout 的 AGENTS.md、开发说明、锁文件和检查命令后准备 | 相关测试/类型检查/lint 实际通过；环境阻塞与测试失败分开记录 |
| `browser-validation` | Playwright、浏览器 MCP 或宿主浏览器工具 | 选一个实际入口，准备浏览器、环境 URL、证据输出和版本读取方法 | 登录态、测试数据及所需交互权限；执行验收用例并保存证据 |
| `web-logs` | 插件自带 tutti-diagnostics → 官方 Chrome MCP → 本机原生 WebMCP | Node/npx；Chrome WebMCP、remote debugging 与连接授权；旧宿主入口作为兼容 | 根据复制引用或 ID 唯一匹配账号和页面，实际调用 get_web_logs；QA 异机需在其侧运行或导出 |
| `computer-directory` | 页面目录；或 tutti-ops 管理目录 | 页面 `list_my_computers`/`list_rooms`/`list_room_agents`；选管理 CLI 时同时启用 `remote-computer` 的 CLI 准备 | 正确账号/环境的目录可见范围；本机身份另用状态命令或可信绑定证据 |
| `local-computer` | 明确路径的本地日志读取 | 复用文件工具；实际状态目录、临时目录与日志路径 | 本机身份匹配与文件读取权限；实际覆盖时间/轮转情况 |
| `remote-computer` | 默认 tutti-ops；实际远端 MCP 可替代 | `setup-tutti-ops --install`，缺少时执行 `npm install -g @tutti-os/tutti-ops-cli`；Node >=20/npm/全局目录写权限 | 默认 `https://admin.tutti.sh`、管理端 Token 获取与本机配置、目录/召回/下载权限；下载后校验、解包并读取 |
| `server-logs` | 实际 Tutti CLI（当前默认 tutti-ops） | 发现命令/schema，按所需日志类别选择；必要时同时启用 `aws-logs` | 同条Bug的服务/环境/窗口、日志读取权限；必需或建议补后立即采集/上传，HTTP失败入口不代替成功请求 |
| `aws-logs` | AWS CLI v2 | `setup-aws-cli --install` 复用或官方安装；下载网络、用户安装目录与系统安装器依赖 | 确认日志在 AWS；目标账号/区域/日志组与读取权限，选中后主动检查并处理认证缺口 |
| `github-delivery` | gh 或实际 GitHub 宿主工具 | 选 gh 时准备其安装；复用已有 Git | 实际推送与 PR 权限；创建成功后附加到当前任务 |
| `deployment` | 项目既有部署/预览流程 | 真实工具、流水线或预览产出方式；不固定猜测某个部署 CLI | 任务授权、目标环境权限、部署结果和修复 SHA 一致 |

其他 CLI、浏览器桥、MCP、渲染器和部署工具的安装方法由所选提供方决定，尚未提供时列“待决策”。具体输入和完成标准仍按 [Setup 的逐步条件](../SKILL.md) 执行。

