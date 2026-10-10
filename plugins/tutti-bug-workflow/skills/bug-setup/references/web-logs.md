# WebMCP 连接准备

提 Bug 时，Agent 通过官方 `chrome-devtools-mcp` 连接**本机正在运行的 Chrome**，调用 Tutti 页面注册的原生 WebMCP 工具（`get_web_logs`、`list_my_computers` 等）读取页面日志。连不上时，bug-investigate 退回使用 QA 导出的诊断包，所以本页的准备是增强项，不阻塞提 Bug。

只能读取运行 Agent 这台机器上的 Chrome。QA 在另一台机器上复现时，WebMCP 读不到，只能用导出包。

## 1. 注册 MCP

插件的 `mcp.json`／`.mcp.json` 已自带下面的 server，随插件安装生效：

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@1.10.1", "--autoConnect", "--categoryExperimentalWebmcp"]
    }
  }
}
```

- 版本固定为 `1.10.1`（已核对其 `list_pages`、`list_webmcp_tools`、`execute_webmcp_tool` 的参数）。升级前先确认新版本的这三个工具参数不变，再同时改 `mcp.json`、`.mcp.json` 与 `workbench.py` 的 `CHROME_DEVTOOLS_MCP`。
- `--autoConnect`：连接用户已打开的 Chrome，不启动新的浏览器。
- `--categoryExperimentalWebmcp`：开启 `list_webmcp_tools`、`execute_webmcp_tool`。
- 需要 Node `^20.19.0 || ^22.12.0 || >=23` 与 `npx`；首次调用由 npx 下载包。
- 其他 MCP 由 `workbench.py configure-mcp` 生成时会保留这一项。

宿主没有加载插件 MCP 时（例如单独使用 Codex），把上面的 `chrome-devtools` 段加入宿主的 MCP 配置后重启会话。

## 2. 在 Chrome 中开启 WebMCP

1. 地址栏打开 `chrome://flags/#enable-webmcp-testing`，把 **WebMCP for testing** 设为 **Enabled**，按提示重启 Chrome。

   ![Chrome 启用 WebMCP：将红框中的 WebMCP for testing 设置为 Enabled](../assets/webmcp-for-testing.png)

2. 没有这个选项时，Chrome 版本不支持 WebMCP，按 [Chrome 官方说明](https://developer.chrome.com/docs/ai/webmcp/) 升级或换用支持的版本；不要猜其他开关。

## 3. 允许远程调试连接

1. 地址栏打开 `chrome://inspect/#remote-debugging`，开启允许远程调试（Allow remote debugging）。
2. Agent 第一次连接时，Chrome 会弹出是否允许调试连接的提示，选择允许。拒绝或超时会表现为 `chrome-devtools` 工具调用失败或卡住。

开启 WebMCP 与允许调试连接是两件事，都需要做；都由使用者本人在 Chrome 里操作，Agent 不修改浏览器设置。

## 4. 验证

1. 在这台机器的 Chrome 中打开并登录 Tutti（`https://tutti.sh/platform/...`；其他部署域名同样适用）。
2. 依次调用：
   - `chrome-devtools.list_pages`：能看到 Tutti 页面及其 `pageId`；
   - `chrome-devtools.list_webmcp_tools({pageId})`：能看到 `get_web_logs`，描述里有 `Page identity: web-diagnostics:<uuid>; Account identity: <account>;`；
   - `chrome-devtools.execute_webmcp_tool({pageId, toolName: "get_web_logs", input: "{\"range\":\"10m\",\"limit\":1}"})`：返回 `Completed` 和日志快照。
3. 三步都成功才算 WebMCP 可用，分别记录结果。

验证时只读：不要对 Tutti 页面调用 `navigate_page`、`close_page`、`new_page`，刷新或跳转会清空页面内存中的日志。

## 常见失败

| 现象 | 处理 |
|---|---|
| 调用卡住或报连接失败 | Chrome 未开启远程调试，或没有点允许；按第 3 步处理 |
| `list_webmcp_tools` 为空或报不可用 | WebMCP flag 未开启或未重启 Chrome；按第 2 步处理 |
| 能看到页面但没有 `get_web_logs` | 页面未登录，或部署的 Tutti 版本不含该能力 |
| `npx` 不存在或版本过低 | 安装符合要求的 Node.js |
