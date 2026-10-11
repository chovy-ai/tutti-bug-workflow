# 字段规则

Bug 管理表（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表「Bug 管理」，视图「新框架（一期）」）与提 Bug、方案是同一张表，配置在数据目录 `config.json` 的 `bug_report` 段，缺省时用插件示例配置。字段通过 `bug_report.field_map` 的字段 ID 定位。

## 本 Skill 写的字段

| 配置键 | 飞书字段 | 怎么写 |
|---|---|---|
| `verification` | 验证结果 | `feishu.py write --set verification=@file`，按 [验证模板](../assets/verification.md)；整体替换，重验时在原内容上更新 |
| `pull_requests` | 关联 PR | `feishu.py add-pr --url`，每行一个链接，已有的不重复追加 |
| `attachments` | 截图、视频、日志 | `feishu.py attach --file`，修复后截图等证据；同名同大小不重复上传，不删已有附件 |

## 只读的字段

分析根因、修复方式（含【RD 批准】）、验收标准由 `$tutti-bug-workflow:bug-solution` 写；状态、修复版本、指派人由人工维护。本 Skill 不改它们。

## 批准校验

`check-approval` 读取分析根因、修复方式、验收标准，要求：

- 三者非空；
- 修复方式末尾有【RD 批准】块，含批准人、时间、原话和摘要；
- 摘要与当前三段内容一致，也就是批准后没有被修改过。

任一不满足即不通过（退出码 1），返回 `problems`。脚本只校验记录内的一致性；批准人是否真是负责的 RD，以 bug-solution 记录的来源为准，有疑问时向用户确认。
