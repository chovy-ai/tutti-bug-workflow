# Web 日志连接准备

提 Bug 时，Agent 通过插件注册的 `tutti-web` MCP 读取**本机 Chrome 里的 Tutti 页面**（`*.tutti.sh`）注册的只读工具（`get_web_logs`、`list_my_computers` 等）。连不上时，bug-investigate 退回使用 QA 导出的诊断包，所以本页的准备是增强项，不阻塞提 Bug。

只能读取运行 Agent 这台机器上的 Chrome。QA 在另一台机器上复现时读不到，只能用导出包。支持 macOS 与 Windows 上的 Google Chrome。

## 工作方式

```
Codex 会话 ─ tutti-web MCP（每个会话一个）─┐
Codex 会话 ─ tutti-web MCP ────────────────┼─ 本机 socket ─ bridge hub（Chrome 启动，每个 Chrome 配置一个）─ 插件 ─ Tutti 页面
定时任务   ─ tutti-web MCP ────────────────┘
```

- **插件**「Tutti Bug Workflow Bridge」只在 `*.tutti.sh` 页面运行，在页面启动前接住 Tutti 注册的工具；只转发 `readOnlyHint: true` 的工具。不使用 Chrome 远程调试，不弹授权窗口，也不需要开启 WebMCP flag。
- **bridge hub** 由 Chrome 通过 Native Messaging 启动，Chrome 开着就在，退出跟着退出；不占 TCP 端口（macOS 用 Unix socket，Windows 用命名管道）。
- **tutti-web MCP** 由 `mcp.json` 为每个 Agent 会话启动，多个会话共用同一个 hub 和插件。

## 1. 安装本机 bridge（Agent 自动完成）

`prepare.py` 的 `web-bridge` 项为 `fix` 时，`prepare.py fix` 会运行：

```sh
node PLUGIN_SOURCE/bridge/tutti-web-bridge.mjs install
```

它把 bridge 与插件文件复制到用户目录（macOS `~/.tutti-bug-workflow/`，Windows `%LOCALAPPDATA%\tutti-bug-workflow\`），用当前 `node` 的绝对路径写启动脚本，并注册 Native Messaging（macOS 写 `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/io.tutti.web_bridge.json`，Windows 写 `HKCU\Software\Google\Chrome\NativeMessagingHosts\io.tutti.web_bridge`）。不需要管理员权限，可重复运行；插件升级后再运行一次即可更新，已加载的插件会自动重新加载新文件。

需要 Node.js 20+。用 nvm 的 Node 时，升级或删除该版本后要重新运行 install。

## 2. 在 Chrome 中加载插件（本人操作一次）

1. 地址栏打开 `chrome://extensions`。
2. 打开右上角「开发者模式」。
3. 点「加载已解压的扩展程序」，选择 install 输出的 `extensionDir`（macOS 在选择框里按 ⌘⇧G 可粘贴路径）。
4. 确认出现「Tutti Bug Workflow Bridge」且处于开启状态。

插件 ID 固定为 `eaacofimpphcbejlpdlmelnenckhagpe`。点插件图标可以看到连接状态、本机的 Tutti 页面，并能直接「复制连接链接」。

## 3. 验证

1. 检查安装状态：

   ```sh
   node PLUGIN_SOURCE/bridge/tutti-web-bridge.mjs doctor
   ```

   `ready: true` 表示 Native Messaging 已注册、插件已连上 hub；否则按 `next` 处理。
2. 在这台机器的 Chrome 中打开并登录 Tutti（`https://tutti.sh/platform/...`）。
3. 在 Codex 里依次调用：
   - `tutti-web.list_tutti_pages`：能看到 Tutti 页面，带 `page`（`web-diagnostics:<uuid>`）、`accountId` 与 `connectionUrl`；
   - `tutti-web.call_tutti_tool({connection, tool: "get_web_logs", input: {"range": "10m", "limit": 1}})`：返回日志快照。
4. 两步都成功才算可用，分别记录结果。

验证只读，不刷新或跳转 Tutti 页面；刷新会清空页面内存中的日志。

## 常见失败

| 现象 / 错误码 | 处理 |
|---|---|
| `host_not_installed` | 运行第 1 步 install |
| `extension_not_connected` | Chrome 没运行，或插件未加载/已停用；按第 2 步处理。刚加载插件时打开一个 Tutti 页面并等几秒 |
| `list_tutti_pages` 为空 | 没有打开 `*.tutti.sh` 页面，或页面在插件加载前打开：刷新一次页面 |
| 页面在列表里但 `connectionUrl` 为空 | 页面未登录，或部署的 Tutti 版本不含诊断工具 |
| `page_not_found` | 页面已刷新或关闭，旧链接失效；请 QA 重新复制连接链接，或改用诊断包 |
| `tool_not_read_only` | 插件只转发只读工具，这是预期行为 |
| 仍无法定位 | 查看 hub 日志：macOS `~/.tutti-bug-workflow/bridge/logs/hub.log`，Windows `%LOCALAPPDATA%\tutti-bug-workflow\bridge\logs\hub.log` |

卸载：`node PLUGIN_SOURCE/bridge/tutti-web-bridge.mjs uninstall`，再在 `chrome://extensions` 移除插件。
