# Web 日志

Web 端只取页面日志（请求等其他现场由 Tutti Web 记入日志）、页面链接，以及用于定位 Computer 的设备列表。三个来源，按顺序使用：

1. **本机 WebMCP（优先）**：用户给了 WebMCP 连接链接，页面还开在运行 Agent 的这台机器的 Chrome 里。不脱敏。
2. **本机导出历史日志**：链接对应的页面已刷新或关闭，但本机 Chrome 里还登录着同一个 Account。Agent 自己新开标签页导出，不用等 QA。
3. **QA 导出的诊断包（兜底）**：用户在另一台机器上，本机没有这个账号的日志。

`get_web_logs` 只能读**当前这次页面会话**内存里的日志，页面一刷新就读不到上一次的；但 Tutti 同时把日志按账号存进浏览器（IndexedDB，保留 7 天），「设置 → 诊断」导出的 zip 包含这个账号在该浏览器里的所有页面会话，也就包括已经刷新掉的那次。

## 方式一：本机 WebMCP

连接链接来自 Tutti「设置 → 诊断 → 复制 WebMCP 连接链接」（或「设置 → 实验室 → WebMCP → 复制连接链接」），形如 `tutti-webmcp://page/web-diagnostics:<uuid>?accountId=<account>`，刷新页面后失效。Chrome 的 WebMCP 与远程调试由 bug-setup 准备。

**只读**：不要对用户的页面调用 `navigate_page`、`close_page`、`new_page` 或刷新，那会清空页面内存里的日志。

1. **找到页面**：`chrome-devtools.list_pages` 列出页面；对 Tutti 页面逐个调用 `list_webmcp_tools({pageId})`，找 `get_web_logs` 描述里 `Page identity: <链接中的 web-diagnostics:uuid>; Account identity: <链接中的 accountId>;` 都一致的那一个，记下页面 URL，即「页面链接」。没有匹配（页面已刷新或关闭）时，记下 Account identity 与链接一致的那些页面的 URL，改用方式二；没有一个页面是这个 Account 时改用方式三。不止一个匹配时也改用方式二。
2. **分页读日志**：`Q` 为 `question_time` 的 Unix 毫秒。
   ```
   execute_webmcp_tool({pageId, toolName: "get_web_logs", input: "{\"range\":\"10m\",\"limit\":200,\"untilUnixMs\":Q}"})
   ```
   每页原始结果存为 `$REPORT/web/pages/page-1.json`……；`truncated: true` 时把 `nextBeforeSequence` 作为 `beforeSequence` 继续，直到 `truncated: false`。
3. **合并**：
   ```sh
   python3 scripts/merge_web_logs.py --connection-url <链接> --question-time <question_time> \
     --page $REPORT/web/pages/page-1.json [--page ...] --output $REPORT/web/web-logs.log
   ```
   脚本核对页面与 Account、提问前 10 分钟的固定窗口、序号连续与去重，写出 JSON Lines（首行 metadata）；`collectionStatus: partial` 表示翻页中断。
4. **设备列表**：`execute_webmcp_tool` 调 `list_my_computers`；房间相关时加 `list_rooms`、`list_room_agents({roomId})`，按 `nextCursor` 读完。用于定位 Computer，不上传。

`web-logs.log` 上传到「截图、视频、日志」，并作为 `web_requests.py --web-logs` 的输入（列出失败请求和 request id）。调用失败是维护侧问题，写在回复里，改用方式二。

## 方式二：本机导出历史日志

前提：方式一里至少有一个 Tutti 页面的 Account identity 和链接一致，说明这台机器的 Chrome 里有这个账号的历史日志。

1. **自己开标签页**：`new_page` 打开和那些页面同源的地址（如页面在 `https://tutti.sh/...` 就开 `https://tutti.sh/platform`；PPE 预览带 `?webBranch=` 的同样带上）。只在这个新标签页里操作，不碰用户的页面。
2. **确认账号**：页面加载后 `list_webmcp_tools` 看新页面的 Account identity，必须和链接里的 accountId 一致；不一致（浏览器当前登录的是别的账号）就关掉标签页，改用方式三。
3. **导出**：`take_snapshot` 找到入口，打开「设置」→「诊断」，在「浏览器日志」里选能覆盖 `question_time` 的最小范围（10 分钟／1 小时／半天／1 天／7 天，从现在往回算），点「导出日志」。
4. **取文件**：Chrome 把 `tutti-web-diagnostics-<时间>.zip` 存到下载目录（默认 `~/Downloads`）；取点击之后新出现的那个，复制到 `$REPORT/web/`。等几秒没出现就看页面的报错，失败原因写进排查线索，改用方式三。
5. `close_page` 关掉自己开的标签页。

拿到 zip 后按方式三的格式处理。解包后在 `manifest.json` 的 `sessions[]` 里找链接里的 `web-diagnostics:<uuid>`：找到就以这次会话的记录为准；找不到（超过 7 天，或那个页面在另一个浏览器）在排查线索里写明，仍按时间窗口使用同账号的日志。这种 zip 已脱敏，排查线索里注明「来源：本机导出（已脱敏）」。

## 方式三：QA 导出的诊断包

在 Tutti「设置 → 诊断 → 浏览器日志」选择导出范围（最近 10 分钟／1 小时／半天／1 天／7 天，选能覆盖问题发生时间的最小一档），点「导出日志」，得到 `tutti-web-diagnostics-<时间>.zip`。要在出问题的同一个浏览器、同一个账号里导出；日志只保留 7 天、最多 20 MB。

拿到后原样上传（复制到 `$REPORT/web/`，第 4 步作为「现场材料」评论的附件发出），解包到 `$REPORT/web/`：

| 文件 | 内容 |
|---|---|
| `manifest.json` | 用户、导出时间、首末记录时间、被淘汰次数、页面会话 `sessions[]`、Computer 列表 `computers[]`（`computerId`、平台、版本）、浏览器 UA |
| `errors.jsonl` | warn 与 error |
| `logs.jsonl` | 全部记录，含 `requestId`（折叠的重复请求另有 `requestIds`）、`computerRefs`、`path` |

诊断包导出时已脱敏。zip 直接作为 `web_requests.py --web-logs` 的输入（脚本读取 `logs.jsonl` 里的 `requestId`），`manifest.computers[]` 用来定位 Computer。

三种方式都没有时记为 `pending`（`reason: no_export`），第 5 步请用户提供。
