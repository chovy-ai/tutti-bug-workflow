# 定时任务

本机 launchd 每小时为一个跟进人跑一轮根因分析。每条 Bug 一个独立的 `codex exec` 会话，在本机直接运行（`--dangerously-bypass-approvals-and-sandbox`），复用本机 lark-cli、git、AWS、mmdc 的登录态与权限。

## 管理

| 命令 | 作用 |
|---|---|
| `schedule.py install [--assignee 姓名] [--min-priority P1] [--interval 秒] [--run-now]` | 按通讯录解析跟进人（缺省当前登录用户），写入 `~/Library/LaunchAgents/com.tutti.bug-solution.<open_id>.plist` 并加载；同一跟进人重复安装会替换 |
| `schedule.py list` | 列出已安装的任务：跟进人、最低优先级、间隔、日志位置 |
| `schedule.py run-now --assignee 姓名` | 立即触发一轮 |
| `schedule.py uninstall --assignee 姓名或 open_id` | 卸载并删除 plist |

任务记录安装时的 `PATH`，所以在能正常使用 `codex`、`lark-cli`、`mmdc` 的终端里安装。电脑需开机并登录该用户；睡眠期间错过的轮次在唤醒后补跑一次。

## 每一轮（`scan.py`）

1. 按跟进人加锁；上一轮还在跑就跳过本轮。
2. 列出待分析的 Bug：指派人=跟进人、状态=未解决、方案状态为空／未处理／已驳回，可选只看某优先级及以上（没有优先级的不算）。按优先级、记录时间排序，**全部处理**。
3. 有待分析的才同步代码（`repos.py sync`）；同步失败本轮结束，下一轮重试。
4. 对每条 Bug：
   - 开始前再查一次方案状态，已被 RD 改成待评审／已批准就跳过；
   - 在 `<数据目录>/solution-runs/<record_id>/<时间>/` 准备 `context.md`、`attachments/`、`code.json`；
   - 运行 `codex exec`，截图（最多 6 张）用 `-i` 附上，开场提示要求按「定时模式」处理；
   - 会话输出写 `session.log`，最后一条消息写 `last-message.md`；
   - 超过 `timeout_minutes` 结束会话；会话结束后方案状态不是「待评审」记为 `failed`，下一轮重试。
5. 删除超过 `keep_days` 的运行目录，输出本轮汇总。

一轮的汇总 JSON 追加到 `<数据目录>/solution-runs/logs/<label>.log`。

## 配置（`config.json` 的 `solution_schedule`）

| 键 | 默认 | 含义 |
|---|---|---|
| `interval_seconds` | 3600 | 两轮间隔，安装时写入 plist |
| `timeout_minutes` | 45 | 单条 Bug 会话的上限 |
| `keep_days` | 7 | 运行目录保留天数 |
| `codex_command` | `codex` | codex CLI 路径 |

## 排查

- 看汇总：`tail -n 100 <数据目录>/solution-runs/logs/com.tutti.bug-solution.<open_id>.log`
- 看某条 Bug 的会话：`<数据目录>/solution-runs/<record_id>/<时间>/session.log`
- 先演练不起会话：`python3 scripts/scan.py --assignee <open_id> --dry-run`
- 只跑一条：`python3 scripts/scan.py --assignee <open_id> --record-id REC`
