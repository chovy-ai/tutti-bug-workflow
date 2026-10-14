# 工作流

> **目前只开放 `bug-investigate`。** `bug-solution`、`bug-execute` 暂时屏蔽（移到插件的 `disabled-skills/`，插件不再加载）。下面关于这两个场景和飞书表交接的内容留作恢复时参考。

| 场景 | 面向 | 交付 | 写入的字段 |
|---|---|---|---|
| `bug-investigate` | QA | 带全现场日志与上下文，用全局 `tutti-cli task create --room-id` 在指定 Room 建 Task，不写飞书表 | Room Task（标题、描述、优先级）与 Room 内附件 |
| `bug-solution` | RD | 每小时按跟进人定时分析方案状态为空／未处理／已驳回的 Bug：根因、流程图与架构图、方案与验收 | 分析根因、根因图、修复方式、验收标准，方案状态置「待评审」 |
| `bug-execute` | RD | 每小时按跟进人修复方案状态为「已批准」的 Bug：修复、提 PR 到 main、部署 PPE（server 泳道 → ws 泳道 → 前端预览 → Computer canary）、验证 | 方案状态（修复中／已部署待验收／修复失败）、修复进度、关联 PR、验证结果、证据附件 |

三个场景以同一条飞书记录（`record_id`）交接，全部无状态：不建本地档案，过程文件放会话临时目录。「状态」由人工流转；「方案状态」的已批准／已驳回由 RD 在表格中选择。

## 代码

- 分析：所有 Bug 共用全局检出（`repositories[].checkout_path`），bug-solution 每次分析前同步到最新 main，只读。
- 修复：bug-execute 每次从远端最新 main 切 worktree 和 `codex/bug-<record_id>` 分支（重试时接着原分支），修复后推送并解除 worktree；PPE 泳道为 `ppe-bug-<record_id>`（tutti-server 与 tsh-websocket 共用），不自动销毁。

## 后续自动调度契约

bug-solution 的定时分析和 bug-execute 的定时修复在本机用 launchd 运行，每个跟进人各一个任务；bug-investigate 由用户手动调用。本版没有飞书事件监听器。后续服务须处理：记录事件去重、忽略 Agent 自身写回、同一 Bug 串行运行、不同 Bug 并行、等待与恢复、有限重试，以及按真实身份核对批准。
