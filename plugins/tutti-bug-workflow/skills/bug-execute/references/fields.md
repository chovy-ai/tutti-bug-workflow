# 字段规则

Bug 管理表（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表「Bug 管理」，视图「新框架（一期）」）与提 Bug、方案是同一张表，配置在数据目录 `config.json` 的 `bug_report` 段，缺省时用插件示例配置。字段通过 `bug_report.field_map` 的字段 ID 定位。

## 本 Skill 写的字段

| 配置键 | 飞书字段 | 怎么写 |
|---|---|---|
| `verification` | 验证结果 | `feishu.py write --set verification=@file`，按 [验证模板](../assets/verification.md)；整体替换，重验时在原内容上更新 |
| `pull_requests` | 关联 PR | `feishu.py add-pr --url`，每行一个链接，已有的不重复追加 |
| `attachments` | 截图、视频、日志 | `feishu.py attach --file`，修复后截图等证据；同名同大小不重复上传，不删已有附件 |

## 只读的字段

分析根因、根因图、修复方式、验收标准由 `$tutti-bug-workflow:bug-solution` 写；方案状态（已批准／已驳回）、状态、修复版本、指派人由人工维护。本 Skill 不改它们。

## 批准校验

`check-approval` 读取方案状态、分析根因、修复方式、验收标准，要求方案状态为「已批准」（`bug_report.plan_status.approved`）且三段都非空；不满足即不通过（退出码 1），返回 `problems`。批准由 RD 在飞书里选择，表格的修改记录可查谁改的。
