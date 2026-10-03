# 配置与接入

每一步 Setup 的必需输入、条件性依赖、待决策项与完成标准统一见 [Setup Skill](../skills/bug-setup/SKILL.md)。先讨论如何获取时使用梳理模式；实际初始化时使用执行模式。本文说明配置字段与具体接入方法。

按业务场景准备工具时，使用 [场景工具 Setup](tool-setup.md)。`config/tool-profiles.json` 定义公共必需项与场景条件项；`scripts/tool_setup.py --scene SCENE` 只读取现有配置和命令路径，`--include TOOL_ID` 选择条件工具。它不修改 `cli_dependencies` 的全局要求、不执行安装计划，也不验证授权；与整体 `doctor` 分别报告。

`workbench.py init` 将 `config/workbench.example.json` 复制为数据目录的 `config.json`，已有文件保持不变。数据目录使用 `--data-dir` 指定，或由 `BUG_WORKBENCH_DATA`、`PLUGIN_DATA`、默认用户目录依次决定。插件安装缓存用于只读源码；数据目录应位于源码和缓存之外。

## 项目配置

- `feishu.base_url`、`base_token`、`table_id`：已固定为用户指定的「Bug 列表」；`field_map` 的键为业务语义，值为真实字段 ID。更换表格前必须重新解析和读取字段，不能复用原字段或视图 ID。
- `feishu.workflow.status_values`、`view_ids`：三个阶段的真实选项名和视图 ID；状态字段通过 `field_map.workflow_status` 定位。`empty_status_stage: bug` 表示空状态旧记录归入 bug单视图。具体推进规则见 [工作流与交接](workflow.md)。
- `repositories`：默认配置 tutti 与 tutti-server 两个仓库的远端 main；每项提供 `name`、`url`、`base_branch`、`cache_path` 和可选 `local_path`。固定 bare 缓存供所有 Bug 复用，本地路径仅用于首次预热；Skill 为各 Bug 准备隔离工作区。操作见 [代码缓存](repository-cache.md)，其他分支需用户指定。
- `log_sources`：每项提供 `name`、`kind`、`transport`、`environment` 及对应入口。Web 使用 `browser-webmcp`、`get_web_logs` 与实际 `browser_bridge`，见 [Web 日志获取](web-logs.md)；`files` 使用明确的文件 `paths`，支持绝对路径、`~/`、`${TMPDIR}/` 和 `${TEMP}/`，读取前解析为本机绝对路径；`mcp` 使用 `mcp_server` 与实际 `tool`；兼容旧配置的 `cli` 使用 `argv` 与可选 `cwd`。Computer 的路径规则及远端协议见 [Computer 日志获取](computer-logs.md)。缺少入口时保留空值，检查逐个报告未配置；配置检查不表示已取得日志。
- `validation`：实际环境、URL、浏览器工具，以及部署版本的读取方法。部署操作仍按当前任务授权执行。
- `aws_cli`：默认 AWS 接入，保存 profile 与查询参考区域。执行 `setup-aws-cli --install` 准备 CLI v2；授权允许待完成，按需使用 `--check-auth`，详见 [AWS CLI 安装与日志读取](aws-cli.md)。
- `aws_mcp`：保留旧版显式 MCP 接入设置，当前 setup 不使用此项自动注册；CLI 可用后清理由插件创建且未被改动的旧 AWS MCP。
- `trigger.mode`：本版只支持 `manual`。填写其他模式不会创建监听器。

`doctor` 检查本地命令是否存在及配置是否齐备，不访问飞书、不验证仓库权限，也不替用户登录。它分别报告本地工具和外部接入的准备状态。

## 日志采集

| 来源 | 获取方式 | 当前配置 |
|---|---|---|
| Web 日志 | 浏览器桥访问 Tutti 原生 `get_web_logs`，通过截图水印匹配页面 | 已固定页面工具与解码入口，等待实际浏览器桥和环境配置 |
| 本地 computer 日志 | 直接读取用户明确指定的文件路径 | 当前 Mac 已保存核实的三个主日志及 Codex 临时诊断路径；分发配置的 `computer-local.paths` 仍为空，新机器需确认后填写 |
| 远端 computer 日志 | tutti-ops CLI 或实际 MCP 执行 Tutti 日志召回，再下载、校验和读取日志包 | 已记录 CLI 命令与协议；使用时确认实际入口、环境与权限，MCP 待接入 |

本地和远端 computer 都按 [Computer 日志获取](computer-logs.md) 执行并保存来源证据。现有配置迁移时只更新相应日志项，保留表格、仓库、认证入口和其他用户设置。

先按 [Computer 定位与 QA 询问](computer-target.md) 判断日志用途，查询目录并消歧目标。页面的 `list_my_computers`、`list_rooms`、`list_room_agents` 用于取得当前账号授权可见的候选，不提供 desktopd 日志或远端召回权限。

远端可使用 [tutti-ops CLI 获取 Computer 日志](tutti-ops-computer-logs.md)，setup 负责准备 CLI；使用前由环境维护方在 [admin.tutti.sh](https://admin.tutti.sh) 管理端获取 Token，按该引用的认证步骤导入本机并核对实际权限。安装不表示 `computer-remote` 的 MCP 已连接；已有 CLI、目标环境与权限时按实际命令直接执行，无需等待 MCP。每条 Bug 保存本次实际使用的 CLI/API origin、目标 Computer、taskId 与证据覆盖。缺少鉴权时记录接入缺口，不自动使用另一种身份。

Web 按 [Web 日志获取](web-logs.md) 配置实际浏览器桥；Tutti 页面注册的原生工具没有 HTTP MCP 地址。若桥通过 MCP 提供，则为桥配置真实 server，并映射页面发现、工具发现和执行能力。详细启用指引在 setup、维护对话或明确求助时提供；Bug 中的 QA 反馈按 [QA 反馈规则](qa-dialogue.md)，仅在必要时请求现场操作或本人授权。

远端 computer MCP 接入时，核对实际 URL/运行入口、认证、工具 schema 与返回格式，将服务器配置写入 `mcp_servers`，再设置对应日志来源的 `mcp_server` 与 `tool`。实际使用前发现宿主工具并执行授权范围内的读取；仅填名称不代表连接成功。查询按 Bug 的环境、时间与时区、computer/会话/request 标识和部署版本定位，并保留实际支持的分页、保留时长及截断信息。

MCP 尚未接入时可分析 QA 已附的日志；在实际支持的浏览器复现中取得的新 console/network 与历史报错日志分别标记。工具接入和权限问题记录为阻塞；必要且仅 QA 能提供的现场资料通过表格提问。凭证和无关用户内容不回填到表格。

QA 所需的补充资料由当前未验证假设决定；通用接入或权限问题交给工具/环境维护人。配置保存入口不代表已经获得对应目标的日志。

## CLI

`tutti-ops` 是 setup 依赖，默认 `required: true`，installer 为 `{"type":"npm-global","package":"@tutti-os/tutti-ops-cli"}`。运行 `setup-tutti-ops --install`，复用已有可用入口；缺少时按用户指定的 `npm install -g @tutti-os/tutti-ops-cli` 安装，要求 Node.js >=20 和 npm。该入口按 npm 当前分发安装并记录实际版本，不固定版本；后续根据本机帮助与 schema 使用能力。全局前缀未在 PATH 中时返回实际入口并保存安装回执供 `doctor` 复用。只迁移旧配置中的 tutti-ops 标准项，其他设置保留；自定义入口先报告差异。安装不启动认证，权限问题保存诊断，不自动使用 sudo。

`cli_dependencies` 定义所需命令。`installer: null` 表示复用系统安装，不猜测包名或安装来源。缺少命令时查官方来源，再将固定版本写入配置。例如以下形状仅描述配置，包名应换成实际核实的 CLI：

```json
{
  "name": "company-cli",
  "command": "company-cli",
  "required": true,
  "installer": {
    "type": "npm",
    "package": "@company/cli",
    "version": "1.2.3"
  }
}
```

调用 `install-cli --name company-cli` 后，安装器在数据目录的 `tools/company-cli/` 运行固定版本 npm 安装，禁用 npm lifecycle scripts，检查对应可执行文件，并返回该可执行文件的路径。后续工具使用返回路径或将其 `.bin` 目录临时加入该任务 PATH。需要 postinstall 的 CLI 不适用 npm 安装器。AWS CLI 通过专用 `aws-official` 类型安装，支持复用现有 v2 和官方固定版本安装；返回实际命令路径，方法见 [AWS CLI](aws-cli.md)。

认证使用 CLI 自己的登录流程。飞书可先看 `lark-cli auth status --help`，确认当前身份；需要授权时仅申请任务所需 scope。凭证保存在 CLI 的认证存储中，配置文件只保存服务位置与非秘密设置。

## MCP

`mcp_servers` 的值使用便携 `mcp.json` 的 server 形状。本版生成器支持 `streamable-http` 与 `stdio`：

```json
{
  "mcp_servers": {
    "team-tools": {
      "type": "streamable-http",
      "url": "https://YOUR_REAL_HOST/mcp"
    }
  }
}
```

上面的地址是说明，不能直接启用。填写真实 URL 后调用：

```sh
python3 PLUGIN_SOURCE/scripts/workbench.py configure-mcp --config CONFIG --output-dir PLUGIN_SOURCE
```

生成器会拒绝明显的占位地址，输出根部 `mcp.json` 和兼容 `.mcp.json`。对源码生成，再更新或重装插件；保持 installed cache 不变。需要的 OAuth、Bearer Token 或其他鉴权按服务要求通过宿主的 MCP 配置与凭证存储完成。生成器不会写入令牌，也不修改用户全局 Codex 设置。

AWS 默认通过 CLI 接入，setup 不注册 AWS MCP。保留的 `setup-aws-mcp` 仅用于用户明确要求恢复 MCP 的场景，与上述配置生成分开。

本地 STDIO 的 `command` 和 `args` 必须指向实际存在的运行时和入口；配置生成不能部署服务器。浏览器 MCP 的登录态、浏览器依赖和连接权限同样需要实际准备。

## 飞书命令适配

使用当前 CLI 帮助确认参数。链接先通过 `lark-cli base +url-resolve` 解析，再读取目标表字段与记录。优先显式使用指定身份，默认 `user`；权限失败先修复授权，不自动切换身份。

写入前确认实际字段类型和 CellValue 结构，只更新该 Bug 的已映射字段；附件使用专用命令。成功以进程退出码和 `ok: true` 为准。审批门禁或权限错误需要按实际反馈处理，不能通过静默追加确认参数绕过。

当前 `analysis_report` 对应「原因分析」，包含分节的根因、修复方案、验收标准和沟通记录。更新前读取最新值，仅替换本场景拥有的分节，保留其他分节和人工修改；发现并发修改时重新读取并合并。完整版本保存在本地档案。不能把多个业务报告各自完整覆盖到同一个字段。

当宿主提供飞书官方 Skills/MCP 时优先复用。若当前宿主没有可用操作说明，用 CLI 自带帮助或官方 API 文档补齐契约后执行。
