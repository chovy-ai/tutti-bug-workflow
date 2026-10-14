# 定时任务

本机 launchd 每小时为一个跟进人跑一轮修复。每条已批准的 Bug 一个独立的 `codex exec` 会话，在本机直接运行（`--dangerously-bypass-approvals-and-sandbox`），复用本机 lark-cli、git、gh、codex 的登录态与权限。

## 管理

| 命令 | 作用 |
|---|---|
| `schedule.py install [--assignee 姓名] [--min-priority P1] [--interval 秒] [--run-now]` | 按通讯录解析跟进人（缺省当前登录用户），写入 `~/Library/LaunchAgents/com.tutti.bug-execute.<open_id>.plist` 并加载；同一跟进人重复安装会替换 |
| `schedule.py list` | 列出已安装的修复任务 |
| `schedule.py run-now --assignee 姓名` | 立即触发一轮 |
| `schedule.py uninstall --assignee 姓名或 open_id` | 卸载并删除 plist |

在能正常使用 `codex`、`lark-cli`、`gh` 的终端里安装（任务记录当时的 `PATH`）。一个跟进人只在一台机器上安装。

## 每一轮（`scan.py`）

1. 按跟进人加锁；上一轮还在跑就跳过本轮。
2. 拿到锁说明没有本跟进人的会话在跑：仍是「修复中」的记录是上一轮中断留下的，改为「修复失败」并写进修复进度。
3. 列出待修复的 Bug：指派人=跟进人、状态=未解决、方案状态=已批准，可选只看某优先级及以上。按优先级、记录时间排序，**全部处理**。
4. 对每条 Bug：
   - 再确认方案状态仍是「已批准」，置为「修复中」，修复进度记下分支、泳道和运行目录；
   - 在 `<数据目录>/execute-runs/<record_id>/<时间>/` 准备 `context.md`、`attachments/`、`diagrams/`、`fix.json`；
   - 运行 `codex exec`，截图（最多 6 张）用 `-i` 附上，开场提示要求按「定时模式」处理；
   - 会话输出写 `session.log`，最后一条消息写 `last-message.md`；
   - 超过 `timeout_minutes`（默认 180，部署要等工作流）结束会话；会话结束时仍是「修复中」就改为「修复失败」并写明原因。
5. 删除超过 `keep_days` 的运行目录，输出本轮汇总。

汇总 JSON 追加到 `<数据目录>/execute-runs/logs/<label>.log`。

## 配置（`config.json` 的 `execute_schedule`）

| 键 | 默认 | 含义 |
|---|---|---|
| `interval_seconds` | 3600 | 两轮间隔，安装时写入 plist |
| `timeout_minutes` | 180 | 单条 Bug 会话的上限 |
| `keep_days` | 7 | 运行目录保留天数 |
| `codex_command` | `codex` | codex CLI 路径 |

## 排查

- 看 bug 单的「修复进度」：每一步都有时间和链接。
- 看会话：`<数据目录>/execute-runs/<record_id>/<时间>/session.log`
- 演练不认领、不起会话：`python3 scripts/scan.py --assignee <open_id> --dry-run`
- 只跑一条：`python3 scripts/scan.py --assignee <open_id> --record-id REC`
