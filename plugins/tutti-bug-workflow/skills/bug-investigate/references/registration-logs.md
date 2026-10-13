# 现场材料与附件

每次提 Bug 固定采集三类现场日志：Web（页面日志）、Server（tutti-server 日志）、Computer（召回包）。全部原样发布到当前 Room，不脱敏。文件放在 Room 目录下的 `$REPORT`（`bug-reports/<operation_id>/`），发布后 Room 里的 Task 与附件是唯一的事实来源。

## 采集结果状态

每类一个结果，记在会话上下文中，写进描述和最终回复：

| status | 含义 |
|---|---|
| `captured` | 取得并覆盖问题发生时间 |
| `empty` | 查询成功，结果为空 |
| `partial` | 取得一部分：截断、翻页中断或覆盖不足 |
| `pending` | 等用户提供：WebMCP 链接或诊断包、设备选择 |
| `blocked` | 无法采集，附原因（认证、权限、设备离线等） |

## 日志文件与附件数量

用 `tutti-cli artifact publish --files '[{"type":"file","path":"<绝对路径>","name":"<名称>","description":"<一句话>"}]' --json` 发布到当前 Room（见 SKILL 第 4 步）。路径必须是 Room 目录内的绝对路径，QA 发来的截图、视频先复制到 `$REPORT`。同一个文件只发布一次；描述的「附件」段按发布时的名称列出：

| 材料 | 上传什么 |
|---|---|
| QA 发来的截图、视频 | 原文件 |
| Web 日志 | `merge_web_logs.py` 合并的 `web-logs.log`；或 QA 导出的 `tutti-web-diagnostics-*.zip` |
| Server | `collect_server.py` 生成的 `server-logs.log` |
| Computer | 召回包原件（`*.tar.gz`），不拆包 |

不发布：查询的原始结果、解包后的目录、中间文件（它们留在 `$REPORT`，不删除）。缺失的来源写进描述「待 QA 确认」或「现场核对」末尾，并在最终回复里说明。
