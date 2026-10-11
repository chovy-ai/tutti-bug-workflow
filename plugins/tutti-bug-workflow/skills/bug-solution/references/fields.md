# 字段规则

Bug 管理表（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表「Bug 管理」，视图「新框架（一期）」）与提 Bug 是同一张表，配置在数据目录 `config.json` 的 `bug_report` 段，缺省时用插件示例配置。字段通过 `bug_report.field_map` 的字段 ID 定位。

## 本 Skill 写的字段

| 配置键 | 飞书字段 | 怎么填 |
|---|---|---|
| `root_cause` | 分析根因 | 按 [根因模板](../assets/root-cause.md)：结论、因果链、证据、代码位置（仓库@sha 路径:行号）、影响范围、待确认 |
| `solution` | 修复方式 | 按 [方案模板](../assets/plan.md)；末尾【RD 批准】块只由 `feishu.py approve` 写，手写会被拒绝 |
| `acceptance` | 验收标准 | 按 [验收模板](../assets/acceptance.md)，每条用例写清操作、断言和证据要求 |

`write` 整体替换字段内容：改之前先 `read`，在现有内容上修改，保留人工写的部分。

## 只读的字段

Bug 描述、问题上下文、环境与版本、页面链接、截图／视频／日志由提 Bug 写入；状态、修复版本、指派人等由人工维护；验证结果、关联 PR 由 `$tutti-bug-workflow:bug-execute` 写。本 Skill 都不改。

## RD 批准

```
【RD 批准】
批准人：张三（ou_xxx）
时间：2026-10-10 18:00:00
原话：可以，按根本方案修
来源：当前对话
摘要：sha256:<分析根因 + 修复方式正文 + 验收标准 的摘要>
```

- `approve` 要求三个字段都非空，批准人按通讯录唯一匹配。
- 摘要绑定批准时的三段内容。之后任何一段被修改，`write` 会清除这一块；人工直接在表格里改了内容，`bug-execute` 的批准校验也会失败。两种情况都需要 RD 重新批准。
