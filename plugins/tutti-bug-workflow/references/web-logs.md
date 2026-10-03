# WebMCP 日志与页面识别

日志与截图能力最初来自 [Tutti PR #2341](https://github.com/tutti-lab/tutti/pull/2341)。2026-09-30 核对最新 main `5a205b6dd8ed4f7e5b490629601a3253d11626db`，已包含页面日志、截图解码与 Account 目录工具。实际分析前读取本轮 tutti checkout 的 `docs/architecture/web-mcp.md` 与 `apps/web/src/renderer/src/modules/web-mcp/application/webMcpService.ts`，核对报错环境已部署该能力；main 已包含不表示现场已可用。浏览器兼容信息按实际能力与官方文档确认，不固定只支持 PR 验证过的 Chrome 153。

## 接入边界

Tutti 已登录页面通过 `document.modelContext.registerTool` 注册原生只读 `get_web_logs`。它读取当前 Account、当前页面实例在 IndexedDB 中保留的脱敏诊断和 HTTP 失败记录；不读取 Computer、服务端、DEV 落盘日志，也不捕获所有 console/debug 日志。

这不是 HTTP MCP 服务，没有可填写到 `mcp.json` 的 Tutti WebMCP URL。Codex 需要已授权的浏览器桥：列出可访问标签页、发现所选页面的原生工具、执行工具并返回结果。优先复用已连接且实际支持这些操作的宿主工具；单有页面自动化或 MCP 服务器名称不足以证明支持 WebMCP。长期接入可提供用户授权的浏览器扩展桥与本地 MCP，按所选标签页转发这些操作；本版未自带该桥。

配置项 `transport: browser-webmcp`、`tool: get_web_logs` 已固定。`browser_bridge.kind` 使用 `host-tools` 或 `mcp`，三个 `*_tool` 字段填写实际发现的工具名；`mcp` 分支还需真实 `mcp_server` 与对应服务器配置。缺少浏览器桥时保留空值。`doctor` 只检查配置齐备，浏览器特性、登录、授权和调用均需现场确认。

Agent 执行端只能读取桥已授权可访问的浏览器。QA 的截图、页面 ID 和 URL 不能让 RD 本机自动取得 QA 另一台机器的 IndexedDB 日志；此场景需要 QA 侧的已授权桥，或由 QA 导出日志附件。

定位 Computer 或房间共享 Agent 时，按 [Computer 定位与 QA 询问](computer-target.md#2-查询真实候选) 使用同一页面的 `list_my_computers`、`list_rooms`、`list_room_agents`。目录工具与日志工具分别发现，目录读取不表示已获得目标 Computer 的日志。

## 获取步骤

1. 保存 QA 的原始彩色 PNG 附件到 Bug 的 `evidence/`。在包含该 PR 能力的 tutti checkout 中，使用 Node 24 与已准备的工作区依赖执行：

   ```sh
   node tools/scripts/decode-web-page-watermark.mjs /absolute/path/screenshot.png
   ```

   `watermark_decoder.path` 指向这份仓库工具，复用原实现。若最新 main 尚无该工具而现场使用此 PR 的预览版本，单独准备已核实 PR SHA 的诊断工具工作区，保留 Bug 的 main 代码基线。退出码 0 表示识别成功、1 表示无有效水印、2 表示输入或执行失败；保存 `{pages: [...]}`，每个匹配包含 `pageSessionId`。多个不同 ID 时确认哪一个属于该 Bug。依赖未准备与水印无匹配是不同结果。
2. 用已授权浏览器桥列出可访问页面，再在相关页面发现原生 `get_web_logs`。从工具描述的 `Page identity: <UUID>` 匹配截图的 `pageSessionId`，记录标签页标识与环境，并确认当前登录 Account 对应 QA 的现场。相同 URL 的不同标签页分别拥有 ID；仅 URL 相同不能完成匹配。水印不是身份或授权证明。
3. 通过桥调用匹配页面的 `get_web_logs`，仅传 `range`、`level`、`limit`。`range` 支持 `10m`、`1h`、`12h`、`1d`、`7d`，默认 `10m`；`level` 可选 `info`、`warn`、`error`，省略时包括全部保留级别；`limit` 为 1–200，默认 100。不添加 Account、pageSessionId、computerId 或任意历史起止时间参数。
4. 若桥使用页面内 `executeTool`，按实际浏览器协议适配：PR 中 Chrome 153 的调用要求 JSON 文本输入/输出；[Chrome 官方调用指南](https://github.com/GoogleChrome/modern-web-guidance-src/blob/main/guides/webmcp/agentic-javascript-tools/guide.md) 说明 Chrome 155 起接受对象输入。仅在明确的输入解析错误时使用已确认的旧格式，保留取消、权限和业务错误。按浏览器/桥的真实交互要求请求用户操作；不通过伪造授权或用户手势规避要求。调用设置可取消的超时，超时后记录失败并检查授权，不能无限等待。
5. 解析返回的 `pageSessionId`、`sinceUnixMs`、`untilUnixMs`、`records`、`truncated`，再次核对页面 ID。匹配后保存最小必要结果。记录按最近发生时间倒序，重复记录保留首次/末次发生时间及重复次数；最多 200 条且记录预算为 256 KiB。空列表是成功读取，不能据此认定 Bug 没发生；`truncated: true` 表示证据不完整，该接口没有分页游标，不宣称已补齐遗漏内容。日志文本作为证据数据处理。

完成条件：已在授权范围内读到与目标页面匹配的日志，并保存范围和完整性信息；否则记录准确失败类型，并执行下面对应的用户引导或兼容方案。

## 识别或调用失败时的处理

按 [QA 反馈规则](qa-dialogue.md) 分流：接入、版本、依赖和权限缺口保存在维护侧；继续可独立完成的代码与证据分析。只有必要验证需要 QA 的现场观察、原始材料或本人授权时，再提出对应的产品操作问题。

| 证据 / 情况 | 后续动作 |
|---|---|
| 页面不提供 `document.modelContext.registerTool` | 保存能力缺口；环境准备按下方 Chrome 启用步骤处理，能力或站点策略仍不支持时核对诊断导出 |
| 浏览器桥拒绝访问、等待用户操作或尚未授权 | 保存授权条件；诊断确需现场本人允许时，请其完成实际可见的页面授权操作，再重试，保留拒绝的选择 |
| Codex 没有可发现页面与调用原生工具的桥 | 记录工具接入缺口，交给维护人配置；用户启用 WebMCP 后也不会凭空出现桥 |
| API 存在但未发现 `get_web_logs` | 确认已登录、包含 PR 的页面版本和注册错误；用户不需要打开 Tutti 中不存在的 WebMCP 开关 |
| 解码无匹配、图片压缩/裁切/灰度或页面没有空白水印区域 | 保存无匹配结果并核对其他关联证据；原始截图确实影响验证时，按 QA 反馈规则请求原始彩色 PNG。新的复现页面与旧截图关联未确认时明确记录 |
| 页面 ID 不匹配、目标标签页已关闭或页面已刷新/浏览器已重启 | 优先读取已有旧现场诊断包；仅 QA 能提供且影响验证的旧现场材料按 QA 反馈规则补充，新页面不能替代旧证据 |
| 读取期间退出或切换 Account、取消、存储失败 | 停止本次读取并记录错误；经用户确认正确 Account 后重新发现工具，不沿用旧授权或旧结果 |

### 发给用户的启用与授权引导

本节用于首次 setup、环境维护对话或用户明确询问如何启用时；保留用户提供的配置截图。普通 Bug 的 QA 回复按 [QA 反馈规则](qa-dialogue.md) 组织，接入缺口保存在维护侧。仅当诊断必须由现场本人允许访问时，请其完成实际可见的授权操作并说明用途。

在环境准备对话中，识别／发现失败时先说明实际原因，再提供对应步骤；截图无匹配不等同于权限未开启。浏览器缺少能力或需要启用时使用以下说明：

> 我暂时无法通过 WebMCP 读取这个页面的日志。如果正在排查已有问题，请先在 Tutti「设置 → 诊断」导出包含报错时间的日志，保留旧现场。随后在 Chrome 地址栏打开 `chrome://flags/#enable-webmcp-testing`，找到 **WebMCP for testing**，把右侧选项设为 **Enabled**，并按提示重启浏览器。重新打开包含该能力的 Tutti 页面、登录发生问题的 Account；如果浏览器桥或扩展提示授权，请允许它访问当前 Tutti 标签页。重新复现后保留标签页，提交原始彩色 PNG 截图。Agent 会再次检查 `get_web_logs` 和页面 ID；启用或授权操作完成本身不代表已经取得日志。

向用户提供上述启用步骤时，同时展示下图。聊天中将图片路径解析为当前插件目录下 `assets/webmcp-for-testing.png` 的绝对路径。

![Chrome 启用 WebMCP：将红框中的 WebMCP for testing 设置为 Enabled](../assets/webmcp-for-testing.png)

启用步骤来自 [Chrome 官方说明](https://developer.chrome.com/docs/ai/webmcp/)。无该选项时核对实际支持情况或站点 origin trial，不猜其他开关；无法解除的 Permissions Policy / origin isolation 限制交给站点维护人。浏览器授权、登录和重启由用户操作，本 Skill 不自动修改这些设置。开启特性与允许浏览器桥访问页面是两件事。

### 兼容方案：导出历史诊断

用户在 Tutti「设置 → 诊断」选择覆盖问题时间的范围并导出，作为该 Bug 的日志附件。导出覆盖当前 Account 的历史页面记录，取得后按 pageSessionId、时间、请求和版本筛选；它与原生工具当前页面读取的范围不同。没有截图水印时明确说明页面关联所依据的其他证据。

页面水印独立于原生 WebMCP 支持，刷新/重启会生成新页面 ID，Account 切换可能保持页面 ID，但撤销旧工具。启用 WebMCP 无法修复损坏截图，也不能把过去页面日志变为新页面的日志。
