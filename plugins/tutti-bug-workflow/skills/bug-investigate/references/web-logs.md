# Web 日志

Web 端只取页面日志（请求等其他现场由 Tutti Web 记入日志）、页面链接，以及用于定位 Computer 的设备列表；全部不脱敏。两个来源，按顺序使用：

1. **本机 Chrome 插件（优先）**：用户给了连接链接，页面开在运行 Agent 的这台机器的 Chrome 里。
2. **QA 导出的诊断包（兜底）**：插件不可用、用户在另一台机器、页面已刷新或关闭。

## 方式一：本机 Chrome 插件

连接链接来自 Tutti「设置 → 诊断 → 复制 WebMCP 连接链接」（或「设置 → 实验室 → WebMCP → 复制连接链接」），也可以点 Chrome 里的「Tutti Bug Workflow Bridge」插件图标「复制连接链接」，形如 `tutti-webmcp://page/web-diagnostics:<uuid>?accountId=<account>`，刷新页面后失效。插件与本机 bridge 由 bug-setup 准备。

全部通过插件注册的 `tutti-web` MCP，只读：它不会刷新、跳转或关闭页面，也只转发页面的只读工具。

1. **找到页面**：`tutti-web.list_tutti_pages` 列出本机的 Tutti 页面，找 `page` 与 `accountId` 都和链接一致的那一个，记下 `url`，即「页面链接」。没有匹配时改用方式二。用户没给链接、列表里只有一个已登录页面时，向用户确认是不是出问题的页面后再用它的 `connectionUrl`。
2. **分页读日志**：`Q` 为 `question_time` 的 Unix 毫秒。
   ```
   call_tutti_tool({connection: <链接>, tool: "get_web_logs", input: {"range": "10m", "limit": 200, "untilUnixMs": Q}})
   ```
   返回值即日志快照。每页原始结果存为 `$TMP/web/pages/page-1.json`……；`truncated: true` 时把 `nextBeforeSequence` 作为 `beforeSequence` 继续，直到 `truncated: false`。
3. **合并**：
   ```sh
   python3 scripts/merge_web_logs.py --connection-url <链接> --question-time <question_time> \
     --page $TMP/web/pages/page-1.json [--page ...] --output $TMP/web/web-logs.log
   ```
   脚本核对页面与 Account、提问前 10 分钟的固定窗口、序号连续与去重，写出 JSON Lines（首行 metadata）；`collectionStatus: partial` 表示翻页中断。
4. **设备列表**：`call_tutti_tool` 调 `list_my_computers`；房间相关时加 `list_rooms`、`list_room_agents({roomId})`，按 `nextCursor` 读完。用于定位 Computer，不上传。

`web-logs.log` 上传到「截图、视频、日志」，并作为 `collect_server.py --web-logs` 的输入（脚本从中提取 request id）。调用失败时按返回的错误码处理：`page_not_found` 请 QA 重新复制链接；`host_not_installed`、`extension_not_connected` 是准备问题，交给 `$tutti-bug-workflow:bug-setup`，写在回复里，本轮改用方式二。

## 方式二：QA 导出的诊断包

在 Tutti「设置 → 诊断 → 浏览器日志」选择导出范围（最近 10 分钟／1 小时／半天／1 天／7 天，选能覆盖问题发生时间的最小一档），点「导出日志」，得到 `tutti-web-diagnostics-<时间>.zip`。要在出问题的同一个浏览器、同一个账号里导出；日志只保留 7 天、最多 20 MB。

拿到后原样上传（已附在飞书记录上时用 `feishu.py download` 取到本地，不重复上传），解包到 `$TMP/web/`：

| 文件 | 内容 |
|---|---|
| `manifest.json` | 用户、导出时间、首末记录时间、被淘汰次数、页面会话 `sessions[]`、Computer 列表 `computers[]`（`computerId`、平台、版本）、浏览器 UA |
| `errors.jsonl` | warn 与 error |
| `logs.jsonl` | 全部记录，含 `requestId`、`computerRefs`、`path` |

诊断包导出时已脱敏。zip 直接作为 `collect_server.py --web-logs` 的输入（脚本读取 `logs.jsonl` 里的 `requestId`），`manifest.computers[]` 用来定位 Computer。

两种方式都没有时记为 `pending`（`reason: no_export`），第 5 步请用户提供。
