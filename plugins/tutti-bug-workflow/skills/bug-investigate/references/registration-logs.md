# 现场材料与附件

每次提 Bug 固定采集三类现场日志：Web（页面日志）、Server（tutti-server 日志）、Computer（召回包）。全部原样作为 Task 附件上传，不脱敏。文件放在 Room 目录下的 `$REPORT`（`bug-reports/<operation_id>/`），上传后 Room 里的 Task 与它的附件是唯一的事实来源。

## 采集结果状态

每类一个结果，记在会话上下文中，写进排查线索和最终回复：

| status | 含义 |
|---|---|
| `captured` | 取得并覆盖问题发生时间 |
| `empty` | 查询成功，结果为空 |
| `partial` | 取得一部分：截断、翻页中断或覆盖不足 |
| `pending` | 等用户提供：WebMCP 链接或诊断包、设备选择 |
| `blocked` | 无法采集，附原因（认证、权限、设备离线等） |

## 日志文件与附件

截图和日志分开挂：**描述只挂 QA 的截图、录屏**（表现的一部分），**日志全部挂在「排查线索」评论上**（见 [Task 字段](report-fields.md#排查线索评论)）。

| 材料 | 挂在哪 | 上传什么 |
|---|---|---|
| QA 发来的截图、视频 | 描述（`task edit --file`） | 原文件，先复制到 `$REPORT` |
| Web 日志 | 排查线索评论（`task comment add --file`） | `merge_web_logs.py` 合并的 `web-logs.log`；或 QA 导出的 `tutti-web-diagnostics-*.zip` |
| Server | 排查线索评论 | `collect_server.py` 生成的 `server-logs.log`；按 Computer 日志补拉的那份复制成 `server-logs-computer.log` |
| Computer | 排查线索评论（召回晚到时另发一条） | 召回包原件（`*.tar.gz`），不拆包 |

规则：

- **每次 `task edit` 都带上截图。** 附件嵌在描述里，`task edit` 整段替换描述，没带上的截图会从描述里消失。
- **评论只追加。** 日志挂在评论上，后来补到的召回包、补拉的日志再发一条评论即可，不需要重传之前的文件。评论可以只附文件，不会触发 Agent。
- **限制**：非空的普通文件，不能是目录或符号链接；同一次调用里文件名不能重复（Task 里显示的就是文件名，同名的先复制改名）；一次合计不超过 500 MiB、最多 256 个；不接受 HTML、XHTML、SVG 等会在浏览器里执行的内容，需要时先打成 zip。
- **失败不改 Task。** 上传、确认或提交任何一步失败，Task 和评论都保持原样。按报错修正后重跑；结果不确定时先回读（描述用 `task show`，评论用 `task timeline`），确实没生效再换新的操作 ID 重跑。

不上传：查询的原始结果、解包后的目录、中间文件（它们留在 `$REPORT`，不删除）。缺失的来源写进排查线索的「日志核对」末尾，需要 QA 提供的写进描述「待 QA 确认」，并在最终回复里说明。

有 Workspace 的云端房间里，QA 的文件已经在 Room 里时，可以用 `--room-file /room/<路径>` 直接引用，不重新上传（Room 成员可见）；本地房间没有 Workspace，只能用 `--file`。

## 旧版 Computer

`tutti-cli task edit --help` 里没有 `--file` 时，截图和日志退回用 `artifact publish` 发布到当前 Room，排查线索评论末尾按发布时的名称列出它们（描述里不贴引用链接）：

```sh
tutti-cli artifact publish --message "Bug 现场：<标题>" --files '[
  {"type":"file","path":"<$REPORT>/web/web-logs.log","name":"Web 日志","description":"提问前 10 分钟的页面日志"},
  {"type":"file","path":"<$REPORT>/server/server-logs.log","name":"Server 日志","description":"tutti-server 相关请求日志"},
  {"type":"file","path":"<$REPORT>/screenshot-1.png","name":"截图 1"}
]' --json
```

路径必须是 Room 目录内的绝对路径；同一个文件只发布一次，召回包等召回完成后单独发布。发布失败时保留文件，写清原因，继续。
