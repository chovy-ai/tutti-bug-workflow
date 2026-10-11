# 字段规则

Bug 管理表（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表「Bug 管理」，视图「新框架（一期）」）与提 Bug、方案是同一张表，配置在数据目录 `config.json` 的 `bug_report` 段，缺省时用插件示例配置。字段通过 `bug_report.field_map` 的字段 ID 定位。

## 本 Skill 写的字段

| 配置键 | 飞书字段 | 怎么写 |
|---|---|---|
| `plan_status` | 方案状态 | `feishu.py set-plan-status --value 修复中／已部署待验收／修复失败 [--note]`，同时追加一行修复进度 |
| `fix_progress` | 修复进度 | `feishu.py progress --message`，只追加，每行 `[yyyy-mm-dd HH:MM] 内容` |
| `pull_requests` | 关联 PR | `feishu.py add-pr --url`，每行一个链接，已有的不重复追加 |
| `verification` | 验证结果 | `feishu.py write --set verification=@file`，按 [验证模板](../assets/verification.md)，整体替换 |
| `attachments` | 截图、视频、日志 | `feishu.py attach --file`，修复后截图等证据；同名同大小不重复上传 |

## 方案状态的流转

| 从 | 到 | 谁 |
|---|---|---|
| 已批准 | 修复中 | 定时任务认领（要求根因、方案、验收都非空） |
| 修复中 | 已部署待验收 | 会话：PR 已提、PPE 已部署、验收通过 |
| 修复中／已批准 | 修复失败 | 会话或定时任务：任何一步失败、会话超时或中断 |
| 修复失败 | 已批准 | RD 处理后手动改回，下一轮重试 |

`set-plan-status` 拒绝其他变化（返回退出码 3 或报错）。「待评审」「已驳回」属于 `$tutti-bug-workflow:bug-solution` 和 RD。

## 只读的字段

分析根因、根因图、修复方式、验收标准由 bug-solution 写；状态、修复版本、指派人由人工维护。

## 扫描条件

`feishu.py scan [--assignee 姓名] [--min-priority P1]`：指派人包含跟进人、状态为「未解决」、方案状态为「已批准」；有 `--min-priority` 时只保留该优先级及以上。按优先级、记录时间排序。
