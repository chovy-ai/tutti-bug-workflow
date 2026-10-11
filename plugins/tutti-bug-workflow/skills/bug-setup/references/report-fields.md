# Bug 表字段与职责

三个业务场景共用一张表：Bug 管理（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表 `tblieImZwMnvZ8My`，视图「新框架（一期）」）。配置在数据目录 `config.json` 的 `bug_report` 段，字段通过 `bug_report.field_map` 的字段 ID 定位；数据目录配置缺少该段时各 Skill 使用插件示例配置。飞书记录是唯一事实来源，不保留本地 Bug 档案。

## 字段映射

| field_map 键 | 飞书字段 | 类型 | 谁写 |
|---|---|---|---|
| `title` | Bug 描述 | 文本 | bug-investigate |
| `attachments` | 截图、视频、日志 | 附件 | bug-investigate（现场）；bug-execute（修复后证据） |
| `reporter` | 提交人 | 人员 | bug-investigate |
| `assignee` | 指派人 | 人员 | bug-investigate；之后人工维护 |
| `status` | 状态 | 单选 | 建单时 bug-investigate 填「未解决」，之后只由人工流转 |
| `platform` / `priority` / `module` / `issue_type` | 所属端 / 优先级 / 业务模块 / 问题类型 | 单选 | bug-investigate |
| `record_time` | 记录时间 | 日期 | bug-investigate |
| `env_version` / `page_url` / `context` | 环境与版本 / 页面链接 / 问题上下文 | 文本 / 超链接 / 文本 | bug-investigate |
| `root_cause` | 分析根因 | 文本 | bug-solution |
| `solution` | 修复方式 | 文本 | bug-solution（末尾【RD 批准】由其 `approve` 写） |
| `acceptance` | 验收标准 | 文本 | bug-solution |
| `verification` | 验证结果 | 文本 | bug-execute |
| `pull_requests` | 关联 PR | 文本 | bug-execute |

「验收标准」「验证结果」是为修复流程新增的列。修复版本、自定义 tag、反馈用户、父记录、备注等不映射，由人工维护。

## 规则

- 每个 Skill 只写自己负责的字段，写后回读核对；改之前先读，保留人工内容。
- 「状态」除建单默认值外不由 Agent 修改，流转全部人工操作。
- 【RD 批准】记录批准人、时间、原话、来源和三段内容（分析根因、修复方式正文、验收标准）的摘要；内容变化后批准失效，需要 RD 重新批准。
- 字段改名不影响映射；更换表格时重新读取字段并更新全部字段 ID，不能复用旧 ID。
