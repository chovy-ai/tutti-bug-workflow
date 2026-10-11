# 现场材料与附件

每次提 Bug 固定采集三类现场日志：Web（页面日志）、Server（tutti-server 日志）、Computer（召回包）。全部原样上传，不脱敏。文件都是本次会话的临时产物，上传后飞书记录是唯一的事实来源。

## 采集结果状态

每类一个结果，记在会话上下文中，交给 `check_collection.py` 汇报现状：

| status | 含义 |
|---|---|
| `captured` | 取得并覆盖问题发生时间 |
| `empty` | 查询成功，结果为空 |
| `partial` | 取得一部分：截断、翻页中断或覆盖不足 |
| `pending` | 等用户提供：WebMCP 链接或诊断包、设备选择 |
| `blocked` | 无法采集，附原因（认证、权限、设备离线等） |

## 日志文件与附件数量

全部上传到「截图、视频、日志」（`field_map.attachments`），用 `scripts/feishu.py attach`（同名同大小跳过，上传后回读确认）：

| 材料 | 上传什么 |
|---|---|
| QA 发来的截图、视频 | 原文件 |
| Web 日志 | `merge_web_logs.py` 合并的 `web-logs.log`；或 QA 导出的 `tutti-web-diagnostics-*.zip` |
| Server | `collect_server.py` 生成的 `server-logs.log` |
| Computer | 召回包原件（`*.tar.gz`），不拆包 |

不上传：查询的原始结果、解包后的目录、中间文件。缺失的来源在最终回复里说明。
