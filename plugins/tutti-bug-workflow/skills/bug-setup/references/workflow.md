# 工作流

Bug 记录在 Multica：一条 Bug 一个 issue（项目 `multica.project`），三个 Skill 由三个 Multica Agent 在本机 Codex runtime 上执行，靠分配 issue 交接。准备与同步见 [Multica 接入](multica.md)。

| 场景 | Agent（配置 `multica.agents`） | 怎么触发 | 交付 |
|---|---|---|---|
| `bug-investigate` | `investigate` | QA 建 issue 分配给它，或在本机 Codex／Multica 里说「记个 bug：…」 | 采集 Web、Computer 现场，issue 写好标题、Bug 表现和优先级，现场作为附件发在「现场材料」评论里，然后分配给分析 Agent |
| `bug-analyze` | `analyze` | 登记完成后自动分配 | 拉最新代码分析根因，回复根本／兼容方案、修复前后流程图和验收要点，状态 `in_review` 等 RD 评审；RD 的追问在同一 issue 里补充 |
| `bug-execute` | `execute` | RD 认可方案后手动分配 | 从最新 main 切分支修复、提 PR，部署 PPE（server 泳道 → ws 泳道 → 前端预览 → Computer canary），自验证，结果和截图回复到 issue，状态 `in_review`（失败 `blocked`） |

QA 验收通过后把 issue 置为 `done`。过程文件放数据目录（`bug-reports/<operation_id>/`、`bug-analysis/<issue 编号>/`、`bug-fixes/<issue 编号>/`）。

## 代码

- 分析：bug-analyze 把代码拉到数据目录的固定检出 `repositories/<仓库名>`，每次分析前更新到最新 main，只读。
- 修复：bug-execute 每次从远端最新 main 切 worktree 和 `codex/bug-<issue 编号小写>` 分支（重试时接着原分支），修复后推送并移除 worktree；PPE 泳道为 `ppe-bug-<同样>`（tutti-server 与 tsh-websocket 共用），不自动销毁。
