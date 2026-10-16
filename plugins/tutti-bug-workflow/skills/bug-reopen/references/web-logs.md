# Web 日志

Web 端只取页面日志（请求等其他现场由 Tutti Web 记入日志）、页面链接，以及用于定位 Computer 的设备列表；全部不脱敏。两个来源，按顺序使用：

1. **本机 WebMCP（优先）**：页面开在运行 Agent 的这台机器的 Chrome 里。用户给了 WebMCP 连接链接时按链接找页面；没给链接时按房间找页面（见下面第 1 步）。
2. **QA 导出的诊断包（兜底）**：WebMCP 不可用、用户在另一台机器、页面已刷新或关闭。

## 方式一：本机 WebMCP

连接链接来自 Tutti「设置 → 诊断 → 复制 WebMCP 连接链接」（或「设置 → 实验室 → WebMCP → 复制连接链接」），形如 `tutti-webmcp://page/web-diagnostics:<uuid>?accountId=<account>`，刷新页面后失效。Chrome 的 WebMCP 与远程调试由 bug-setup 准备。

**只读**：不要对用户的页面调用 `navigate_page`、`close_page`、`new_page` 或刷新，那会清空页面内存里的日志。

1. **找到页面**：`chrome-devtools.list_pages` 列出页面，再对候选页面调用 `list_webmcp_tools({pageId})`，从 `get_web_logs` 的描述里读 `Page identity: web-diagnostics:<uuid>; Account identity: <userId>;`。
   - **有连接链接**：找 Page identity 和 Account identity 都和链接一致的那一个。
   - **没有连接链接**：候选是 URL 路径为 `/platform/room/<roomId>` 的 Tutti 页面（`<roomId>` 用这条 Task 的 `roomId`），并且 Account identity 等于 `tutti-cli whoami --json` 的 `userId`。只有一个就用它；不止一个时优先 URL 里带 `task=<taskId>` 的（本次的 Task 正开着），仍不止一个就当作没找到。用户说过问题出在另一台机器或另一个浏览器时不用这种找法。
   - 没有匹配时改用方式二。记下页面 URL（「页面链接」）和 Page identity；没有链接时在排查线索的「日志核对」里注明「按房间找到的页面」。
2. **分页读日志**：`Q` 是读日志的截止时间：打回消息的时间 `question_time`，或看到问题的时间 `incident_at` 之后 5 分钟（两者取早的），精确到毫秒；后面合并时传同样的两个参数，不要另取一次当前时间。用脚本算：
   ```sh
   python3 scripts/merge_web_logs.py --question-time <question_time> --incident-at <incident_at> --until-ms   # 输出 untilUnixMs（Q）和 range（R），每页都使用这两个值
   ```
   ```
   execute_webmcp_tool({pageId, toolName: "get_web_logs", input: "{\"range\":\"R\",\"limit\":200,\"untilUnixMs\":Q}"})
   ```
   `R` 替换为脚本返回的 `range`（`10m` 或 `1h`）；晚报时用 `1h` 读取完整窗口，合并时筛掉故障前 10 分钟以前的记录。每页原始结果存为 `$REPORT/web/pages/page-1.json`……；`truncated: true` 时把 `nextBeforeSequence` 作为 `beforeSequence` 继续，直到 `truncated: false`。
3. **合并**：
   ```sh
   python3 scripts/merge_web_logs.py --connection-url <链接> --question-time <question_time> --incident-at <incident_at> \
     --page $REPORT/web/pages/page-1.json [--page ...] --output $REPORT/web/web-logs.log
   # 没有连接链接时：--connection-url 传 Page identity（web-diagnostics:<uuid>），并加 --account-id <whoami 的 userId>
   ```
   报「Page N was read with untilUnixMs=…」说明读页时用的 Q 和 `--question-time` 对不上：用 `--until-ms` 重新算 Q 和 R，从第一页重新读。
   脚本核对页面与 Account、读取范围（`10m`／`1h`），输出故障前 10 分钟到后 5 分钟且不晚于上报时间的窗口、序号连续与去重，写出 JSON Lines（首行 metadata）；`collectionStatus: partial` 表示翻页中断。
4. **设备列表**：`execute_webmcp_tool` 调 `list_my_computers`；房间相关时加 `list_rooms`、`list_room_agents({roomId})`，按 `nextCursor` 读完。用于定位 Computer，不上传。

`web-logs.log` 作为打回评论的附件上传，并作为 `web_requests.py --web-logs` 的输入（列出失败请求和 request id）。调用失败是维护侧问题，写在回复里，改用方式二。

## 方式二：QA 导出的诊断包

在 Tutti「设置 → 诊断 → 浏览器日志」选择导出范围（最近 10 分钟／1 小时／半天／1 天／7 天，选能覆盖问题发生时间的最小一档），点「导出日志」，得到 `tutti-web-diagnostics-<时间>.zip`。要在出问题的同一个浏览器、同一个账号里导出；日志只保留 7 天、最多 20 MB。

拿到后原样上传（复制到 `$REPORT/web/`，第 4 步作为评论附件挂上），解包到 `$REPORT/web/`：

| 文件 | 内容 |
|---|---|
| `manifest.json` | 用户、导出时间、首末记录时间、被淘汰次数、页面会话 `sessions[]`、Computer 列表 `computers[]`（`computerId`、平台、版本）、浏览器 UA |
| `errors.jsonl` | warn 与 error |
| `logs.jsonl` | 全部记录，含 `requestId`（折叠的重复请求另有 `requestIds`）、`computerRefs`、`path` |

诊断包导出时已脱敏。zip 直接作为 `web_requests.py --web-logs` 的输入（脚本读取 `logs.jsonl` 里的 `requestId`），`manifest.computers[]` 用来定位 Computer。

两种方式都没有时记为 `pending`（`reason: no_export`），第 7 步请用户提供。
