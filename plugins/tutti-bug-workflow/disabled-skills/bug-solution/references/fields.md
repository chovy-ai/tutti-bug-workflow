# 字段规则

Bug 管理表（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表「Bug 管理」，视图「新框架（一期）」）与提 Bug 是同一张表，配置在数据目录 `config.json` 的 `bug_report` 段，缺省时用插件示例配置。字段通过 `bug_report.field_map` 的字段 ID 定位。

## 本 Skill 写的字段

| 配置键 | 飞书字段 | 怎么填 |
|---|---|---|
| `root_cause` | 分析根因 | 按 [根因模板](../assets/root-cause.md)：开头「根因」（两三句大白话，150 字以内）、「复现路径」、「预期工作流程」三段，之后是细节；末尾「分析来源」写分析时间、会话运行目录和代码 SHA |
| `diagrams` | 根因图（附件） | `feishu.py attach`，只收 PNG；文件名 `flow-<record_id>-<时间>.png`、`arch-<record_id>-<时间>.png`，重新分析时新增一组，不删旧图 |
| `solution` | 修复方式 | 按 [方案模板](../assets/plan.md) |
| `acceptance` | 验收标准 | 按 [验收模板](../assets/acceptance.md) |
| `plan_status` | 方案状态（单选） | `feishu.py set-plan-status --value 待评审`，只能置「待评审」，要求三段都非空 |

- `write` 整体替换字段内容。
- `write --if-open`：写入前方案状态不是空／未处理／已驳回就整次跳过（退出码 3）。定时模式一律带上，RD 已经评审或批准的内容不会被覆盖。

## 只读的字段

Bug 描述、问题上下文、环境与版本、页面链接、截图／视频／日志由提 Bug 写入；状态、修复版本、指派人、驳回意见由人工维护；验证结果、关联 PR 由 `$tutti-bug-workflow:bug-execute` 写。

## 扫描条件

`feishu.py scan [--assignee 姓名] [--min-priority P1]`：指派人包含跟进人、状态为「未解决」（`bug_report.defaults.status`）、方案状态为空／未处理／已驳回（`bug_report.plan_status.open`）。有 `--min-priority` 时只保留该优先级及以上，没有优先级的记录不算。按优先级、记录时间排序。

## 方案状态

| 值 | 含义 |
|---|---|
| 空／未处理 | 还没出方案，定时任务会分析 |
| 待评审 | 定时任务已写完根因、图、方案、验收，等 RD 看 |
| 已批准 | RD 认可，`$tutti-bug-workflow:bug-execute` 只修复这个状态的 Bug |
| 已驳回 | RD 不认可，原因写在「驳回意见」；下一轮结合意见和上一版重新分析 |

选项名在 `bug_report.plan_status` 中配置。
