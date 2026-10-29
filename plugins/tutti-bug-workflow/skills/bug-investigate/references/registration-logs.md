# 现场材料与附件

每次提 Bug 固定采集两类现场日志：Web（页面日志）、Computer（召回包）；tutti-server 日志不在提 Bug 时拉，相关请求的 request id 记进排查线索，RD 排查时再查。全部原样作为 Task 附件上传，不脱敏。文件放在数据目录下的 `$REPORT`（`bug-reports/<operation_id>/`），上传后 Room 里的 Task 与它的附件是唯一的事实来源。

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

本会话自建且保留全部原附件的 Task，现场用 `task edit --file` 挂在描述上；复用已有 Task 时，所有本次现场（包括后到的文件）都用 `task comment --file` 追加，不改原标题、描述和附件。评论正文只写这次看到的 Bug 表现，记下回执 `commentId`，供 RD 定位附件。描述正文只写 Bug 表现（见 [Task 字段](report-fields.md)）。

| 材料 | 上传什么 |
|---|---|
| QA 发来的截图、视频 | 原文件，先复制到 `$REPORT` |
| 排查线索 | `排查线索.txt`（见 [排查线索](report-fields.md#排查线索附件)） |
| Web 日志 | `merge_web_logs.py --download` 从下载文件校验、整理出的 `web-logs.log`；或 QA 导出的 `tutti-web-diagnostics-*.zip` |
| Computer | 召回包原件（`*.tar.gz`），不拆包 |

规则：

- **自建 Task 编辑时每次都带上全部文件。** 附件嵌在描述里，`task edit` 整段替换描述，没带上的文件会从 Task 上消失；带 `--file` 时必须同时给 `--description-file`。每次都会重新上传，所以尽量等现场齐了只提交一次。
- **限制**：非空的普通文件，不能是目录或符号链接；同一次调用里文件名不能重复（Task 里显示的就是文件名，同名的先复制改名）；一次合计不超过 500 MiB、最多 256 个；不接受 HTML、XHTML、SVG 等会在浏览器里执行的内容，需要时先打成 zip。超过 500 MiB 时优先去掉最大的召回包，在排查线索里写明本地路径。
- **复用 Task 的评论。** `task comment --room-id <roomId> --task-id <taskId> --content-file <$REPORT>/description.txt --file <本次文件> --operation-id <新 UUID> --json`，`--file` 可重复。回执 `status: posted` 才算发出，记下 `commentId`。超时用同一个操作 ID、相同正文和文件重试一次；`COMMENT_IDEMPOTENCY_CONFLICT` 表示第一次已发出，不再重发。后到现场另发评论，只带新文件和更新的排查线索，不重传已有附件。
- **编辑失败不改 Task。** 上传、确认或提交任何一步失败，Task 保持原样（已上传的文件可能留在服务端，不影响）。按报错修正后重跑；结果不确定时先 `task show` 回读，确实没生效再换新的操作 ID 重跑，不用同一个 ID 配不同的附件。

不上传：查询的原始结果、解包后的目录、中间文件（它们留在 `$REPORT`，不删除）。缺失的来源写进排查线索的「日志核对」末尾，需要 QA 提供的写进描述「待 QA 确认」，并在最终回复里说明。

有 Workspace 的云端房间里，QA 的文件已经在 Room 里时，可以用 `--room-file /room/<路径>` 直接引用，不重新上传（Room 成员可见）；本地房间没有 Workspace，只能用 `--file`。
