# 工作流

两个业务场景只对接 Tutti 任务系统（Room 里的 Task），都用全局 `tutti-cli`（账号登录版）读写；不用飞书表，也没有定时任务。

| 场景 | 面向 | 怎么触发 | 交付 |
|---|---|---|---|
| `bug-investigate` | QA | 手动：「记个 bug：…」 | 带全现场日志与上下文，用 `tutti-cli task create --room-id` 在指定 Room 建 Task，附件挂在描述上；再用 `task run` 把根因分析交给该 Room 的 Agent，分析结果回复在 Task 评论里 |
| `bug-execute` | RD | 手动：「修复这个 Task <链接>」，并给出认可的方案（通常是 Room Agent 的分析回复） | 从最新 main 切分支修复、提 PR 到 main，部署 PPE（server 泳道 → ws 泳道 → 前端预览 → Computer canary），自验证，把原因、PR、体验链接和验证结果用 `task comment` 回复到 Task |

两个场景以同一条 Task（Room ID ＋ Task ID）交接，不建本地档案；过程文件放数据目录（`bug-reports/<operation_id>/`、`bug-fixes/<taskId>/`）。Task 的状态、负责人、优先级由人工在任务看板维护。

## 代码

- 分析：Room Agent 把代码拉到它所在电脑的固定目录 `repositories/<仓库名>`，每次分析前更新到最新 main，只读。
- 修复：bug-execute 每次从远端最新 main 切 worktree 和 `codex/bug-<Task ID 前 8 位>` 分支（重试时接着原分支），修复后推送并解除 worktree；PPE 泳道为 `ppe-bug-<同样 8 位>`（tutti-server 与 tsh-websocket 共用），不自动销毁。
