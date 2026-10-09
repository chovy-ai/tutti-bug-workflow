# 配置与接入

每一步 Setup 的必需输入、条件性依赖、待决策项与完成标准统一见 [Setup Skill](../SKILL.md)。先讨论如何获取时使用梳理模式；实际初始化时使用执行模式。本文说明配置字段与具体接入方法。

按业务场景准备工具时，使用 [场景工具 Setup](tool-setup.md)。`config/tool-profiles.json` 定义公共必需项与场景条件项；`scripts/tool_setup.py --scene SCENE` 只读取现有配置和命令路径，`--include TOOL_ID` 选择条件工具。它不修改 `cli_dependencies` 的全局要求、不执行安装计划，也不验证授权；与整体 `doctor` 分别报告。

`workbench.py init` 将 `config/workbench.example.json` 复制为数据目录的 `config.json`，已有文件保持不变。数据目录使用 `--data-dir` 指定，或由 `BUG_WORKBENCH_DATA`、`PLUGIN_DATA`、默认用户目录依次决定。插件安装缓存用于只读源码；数据目录应位于源码和缓存之外。

## 项目配置

- `feishu.base_url`、`base_token`、`table_id`：已固定为用户指定的「Bug 列表」；`field_map` 的键为业务语义，值为真实字段 ID。更换表格前必须重新解析和读取字段，不能复用原字段或视图 ID。
- `feishu.workflow.status_values`、`view_ids`：三个阶段的真实选项名和视图 ID；状态字段通过 `field_map.workflow_status` 定位。`empty_status_stage: bug` 表示空状态旧记录归入 bug单视图。具体推进规则见 [工作流与交接](workflow.md)。
- `repositories`：默认配置 tutti 与 tutti-server 两个仓库的远端 main；每项提供 `name`、`url`、`base_branch`、`cache_path` 和可选 `local_path`。固定 bare 缓存供所有 Bug 复用，本地路径仅用于首次预热；Skill 为各 Bug 准备隔离工作区。操作见 代码缓存，其他分支需用户指定。
- `log_sources`：每项提供 `name`、`kind`、`transport`、`environment` 及对应入口。Web 使用 `browser-webmcp`、`get_web_logs` 与实际 `browser_bridge`，见 Web 日志获取；`files` 使用明确的文件 `paths`，支持绝对路径、`~/`、`${TMPDIR}/` 和 `${TEMP}/`，读取前解析为本机绝对路径；`mcp` 使用 `mcp_server` 与实际 `tool`；兼容旧配置的 `cli` 使用 `argv` 与可选 `cwd`。Computer 的路径规则及远端协议见 Computer 日志获取。缺少入口时保留空值，检查逐个报告未配置；配置检查不表示已取得日志。
- `validation`：实际环境、URL、浏览器工具，以及部署版本的读取方法。部署操作仍按当前任务授权执行。
- `aws_cli`：默认 AWS 接入，保存 profile 与查询参考区域。执行 `setup-aws-cli --install` 准备 CLI v2；完整 Setup 或选择 AWS 时接续 `--check-auth` 并处理认证缺口，详见 AWS CLI 安装与日志读取。
- `aws_mcp`：保留旧版显式 MCP 接入设置，当前 setup 不使用此项自动注册；CLI 可用后清理由插件创建且未被改动的旧 AWS MCP。
- `trigger.mode`：本版只支持 `manual`。填写其他模式不会创建监听器。

`doctor` 检查本地命令是否存在及配置是否齐备，不访问飞书、不验证仓库权限，也不替用户登录。它分别报告本地工具和外部接入的配置状态；执行模式的 Agent 还需按 主动补齐授权 验证权限、处理缺口并复查实际访问。

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
# MCP 配置由 bug-setup 生成（workbench.py configure-mcp）
```

生成器会拒绝明显的占位地址，输出根部 `mcp.json` 和兼容 `.mcp.json`。对源码生成，再更新或重装插件；保持 installed cache 不变。需要的 OAuth、Bearer Token 或其他鉴权按服务要求通过宿主的 MCP 配置与凭证存储完成。生成器不会写入令牌，也不修改用户全局 Codex 设置。

AWS 默认通过 CLI 接入，setup 不注册 AWS MCP。保留的 `setup-aws-mcp` 仅用于用户明确要求恢复 MCP 的场景，与上述配置生成分开。

本地 STDIO 的 `command` 和 `args` 必须指向实际存在的运行时和入口；配置生成不能部署服务器。浏览器 MCP 的登录态、浏览器依赖和连接权限同样需要实际准备。

## 飞书命令适配

使用当前 CLI 帮助确认参数。链接先通过 `lark-cli base +url-resolve` 解析，再读取目标表字段与记录。优先显式使用指定身份，默认 `user`；权限失败先修复授权，不自动切换身份。

写入前确认实际字段类型和 CellValue 结构，只更新该 Bug 的已映射字段；附件使用专用命令。成功以进程退出码和 `ok: true` 为准。审批门禁或权限错误需要按实际反馈处理，不能通过静默追加确认参数绕过。

报告使用 [独立字段契约](report-fields.md)。`analysis_report` 对应「根因分析」，沿用原「原因分析」字段 ID，只填写因果链与影响范围；结论、排查验证、代码基线、相关代码、修复方案、验收标准、修复后验证、沟通和待核实项各有自己的 field_map 键。写入前读取目标字段，保留人工内容和其他场景的条目；发现并发修改时重新读取并合并。旧分节报告先读取并按授权迁移，不批量改写历史记录。缺少字段时补齐实际映射或保存回填缺口，不能把全部内容退回写进根因分析。

当宿主提供飞书官方 Skills/MCP 时优先复用。若当前宿主没有可用操作说明，用 CLI 自带帮助或官方 API 文档补齐契约后执行。
