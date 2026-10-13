# 现场材料与附件

每次提 Bug 固定采集三类现场日志：Web（页面日志）、Server（tutti-server 日志）、Computer（召回包）。全部原样作为 Task 附件上传，不脱敏。文件放在 Room 目录下的 `$REPORT`（`bug-reports/<operation_id>/`），上传后 Room 里的 Task 与它的附件是唯一的事实来源。

## 采集结果状态

每类一个结果，记在会话上下文中，写进描述和最终回复：

| status | 含义 |
|---|---|
| `captured` | 取得并覆盖问题发生时间 |
| `empty` | 查询成功，结果为空 |
| `partial` | 取得一部分：截断、翻页中断或覆盖不足 |
| `pending` | 等用户提供：WebMCP 链接或诊断包、设备选择 |
| `blocked` | 无法采集，附原因（认证、权限、设备离线等） |

## 日志文件与附件

附件随 `tutti-cli task edit --description-file <描述> --file <路径> [--file <路径> ...]` 一起提交（见 SKILL 第 4、5 步），上传为 Task 的私有附件，只有 Room 成员能下载：

| 材料 | 上传什么 |
|---|---|
| QA 发来的截图、视频 | 原文件，先复制到 `$REPORT` |
| Web 日志 | `merge_web_logs.py` 合并的 `web-logs.log`；或 QA 导出的 `tutti-web-diagnostics-*.zip` |
| Server | `collect_server.py` 生成的 `server-logs.log`；按 Computer 日志补拉的那份复制成 `server-logs-computer.log` |
| Computer | 召回包原件（`*.tar.gz`），不拆包 |

规则：

- **每次 `task edit` 都带全部附件。** 附件嵌在描述里，`task edit` 整段替换描述，没带上的附件会从描述里消失。会话里维护一份附件清单，每次编辑按清单把 `--file` 全部带上；重复上传同一个文件没有关系。
- **只追加文件、不改描述时用评论**：`tutti-cli task comment add --task-id <taskId> --file <路径> [--text "<一句说明>"] --operation-id <新 UUID> --json`，评论可以只附文件，不会触发 Agent。
- **限制**：非空的普通文件，不能是目录或符号链接；同一次调用里文件名不能重复（Task 里显示的就是文件名，同名的先复制改名）；一次合计不超过 500 MiB、最多 256 个；不接受 HTML、XHTML、SVG 等会在浏览器里执行的内容，需要时先打成 zip。
- **失败不改 Task。** 上传、确认或提交任何一步失败，Task 保持原样，已上传的文件不会挂上。按报错修正后重跑；结果不确定时先 `task show` 回读，确实没生效再换新的操作 ID 重跑。
- **回读核对。** `task show --task-id <taskId> --json` 的描述里应能看到清单上的每个文件名；少了就带全清单再 `task edit` 一次。

不上传：查询的原始结果、解包后的目录、中间文件（它们留在 `$REPORT`，不删除）。缺失的来源写进描述「待 QA 确认」或「现场核对」末尾，并在最终回复里说明。

有 Workspace 的云端房间里，QA 的文件已经在 Room 里时，可以用 `--room-file /room/<路径>` 直接引用，不重新上传（Room 成员可见）；本地房间没有 Workspace，只能用 `--file`。

## 旧版 Computer

`tutti-cli task edit --help` 里没有 `--file` 时，附件退回用 `artifact publish` 发布到当前 Room，描述「附件」段改写成「附件（已发布到本 Room）」：

```sh
tutti-cli artifact publish --message "Bug 现场：<标题>" --files '[
  {"type":"file","path":"<$REPORT>/web/web-logs.log","name":"Web 日志","description":"提问前 10 分钟的页面日志"},
  {"type":"file","path":"<$REPORT>/server/server-logs.log","name":"Server 日志","description":"tutti-server 相关请求日志"},
  {"type":"file","path":"<$REPORT>/screenshot-1.png","name":"截图 1"}
]' --json
```

路径必须是 Room 目录内的绝对路径；同一个文件只发布一次，召回包等召回完成后单独发布。发布失败时保留文件，写清原因，继续。
