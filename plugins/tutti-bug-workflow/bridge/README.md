# tutti-web-bridge

让本机 Agent 读取 Chrome 中 Tutti 页面（`*.tutti.sh`）注册的只读 WebMCP 工具，不经过 Chrome 远程调试，因此不弹授权窗口。使用者的准备步骤见 [Web 日志连接准备](../skills/bug-setup/references/web-logs.md)，用法见 [Web 日志](../skills/bug-investigate/references/web-logs.md)。

## 组成

```
Agent ─stdio MCP─ tutti-web-bridge mcp ─┐            （每个 Agent 会话一个）
Agent ─stdio MCP─ tutti-web-bridge mcp ─┼─ socket ─ tutti-web-bridge host ─ Native Messaging ─ 插件后台 ─ 页面脚本 ─ Tutti
CLI   ─ tutti-web-bridge pages / call ──┘            （每个 Chrome 配置一个，由 Chrome 启动）
```

| 部分 | 文件 | 说明 |
|---|---|---|
| MCP / CLI 客户端 | `tutti-web-bridge.mjs mcp`、`pages`、`call` | 扫描运行目录里的 hub，汇总页面，按连接链接定位页面后调用 |
| hub | `tutti-web-bridge.mjs host` | Chrome 启动；stdio 收发插件消息，按请求 ID 把结果送回发起的客户端 |
| 安装 | `install`、`uninstall`、`doctor` | 复制到用户目录、写启动脚本与 Native Messaging 清单（Windows 写 HKCU 注册表），检查状态 |
| 插件 | `../browser-extension/` | MAIN world 脚本在 Tutti 启动前提供 `document.modelContext.registerTool`（已有原生实现时包一层），经私有 MessageChannel 交给插件；后台维持一个 `connectNative` 连接 |

单文件、无依赖，需要 Node.js 20+。

## 关键约定

- **身份**：页面身份来自 `get_web_logs` 描述里的 `Page identity: …; Account identity: …;`，与 Tutti 的连接链接 `tutti-webmcp://page/<pageSessionId>?accountId=<id>` 一致。
- **只读**：页面脚本只执行 `annotations.readOnlyHint === true` 的工具，其他返回 `tool_not_read_only`。
- **不占端口**：hub 监听 `run/<pid>.sock`（macOS，权限 0600）或 `\\.\pipe\tutti-web-bridge-<用户>-<pid>`（Windows），并写 `run/<pid>.json` 供客户端发现；退出时删除，残留由下一个 hub 清理。
- **版本**：客户端握手时带 `bridgeVersion`，hub 版本更旧就退出，插件重连后 Chrome 启动新安装的版本；hub 告诉插件已安装的插件文件版本，插件更旧时 `chrome.runtime.reload()`（10 分钟内最多一次）。
- **插件 ID** 由 `manifest.json` 的 `key` 固定为 `eaacofimpphcbejlpdlmelnenckhagpe`，与 Native Messaging 清单的 `allowed_origins` 对应；改 `key` 必须同时改 `EXTENSION_ID`。
- **错误码**：`host_not_installed`、`extension_not_connected`、`page_not_found`、`page_ambiguous`、`tool_not_found`、`tool_not_read_only`、`tool_failed`、`page_closed`、`timeout`、`hub_closed`。

## 测试

```sh
node --test bridge/tests/*.test.mjs
```

覆盖消息帧、hub 路由、多客户端共用一个 hub、多个 Chrome 配置、安装后的启动脚本、doctor。真实 Chrome 中的端到端验证（加载插件、模拟 Tutti 注册、空闲 75 秒、杀掉 hub 后恢复）用 Chrome for Testing 手动运行：正式版 Chrome 不支持命令行加载插件。
