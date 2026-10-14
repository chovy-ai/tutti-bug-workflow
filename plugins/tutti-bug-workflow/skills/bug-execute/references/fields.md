# 字段规则

Bug 管理表（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表「Bug 管理」，视图「新框架（一期）」）与提 Bug、方案是同一张表，配置在数据目录 `config.json` 的 `bug_report` 段，缺省时用插件示例配置。字段通过 `bug_report.field_map` 的字段 ID 定位。

## 本 Skill 写的字段

| 配置键 | 飞书字段 | 怎么写 |
|---|---|---|
| `plan_status` | 方案状态 | `feishu.py set-plan-status --value 修复中／已部署待验收／修复失败 [--note]`，同时追加一行修复进度 |
| `fix_progress` | 修复进度 | `feishu.py progress --message`，只追加，每行 `[yyyy-mm-dd HH:MM] 内容` |
| `environment` | 访问环境（链接样式） | **一个裸 https 链接**，点开即可体验修复：前端预览 `https://tutti.sh/platform/?webBranch=<分支>`（指向本条泳道）；只改 Computer 时为 canary 发布 run 页面，且不会覆盖已有的前端预览。`deploy.py … --record-id REC` 部署成功后自动写；手动补写或换成更具体的页面用 `feishu.py environment --url <链接> [--service computer]`，非链接内容会被拒绝。泳道、canary 版本写在修复进度。为空时 `set-plan-status 已部署待验收` 报错 |
| `pull_requests` | 关联 PR | `feishu.py add-pr --url`，每行一个链接，已有的不重复追加 |
| `cause` | 一句话解释原因 | `feishu.py write --set cause=…`：修复完成后根据 PR 的实际改动写一句通俗的原因，单行、不超过 80 字，不用代码名词，讲原因不讲改法；为空时 `set-plan-status 已部署待验收` 报错 |
| `verification` | 验证结果 | `feishu.py write --set verification=@file`，按 [验证模板](../assets/verification.md)，整体替换 |
| `fix_screenshots` | 修复截图（附件） | `feishu.py attach --file`（默认这一列），只收 PNG／JPEG，文件名 `fix-<record_id>-<用例编号>-<yyyymmddHHMM>.png`（修复前对照用 `before-`）；同名同大小不重复上传 |
| `attachments` | 截图、视频、日志 | `feishu.py attach --field attachments --file`，只放截图以外的补充证据（如测试输出、日志）；QA 的现场附件不删 |

**部署后体验环境必须在 bug 单上**：任何一端部署成功后，不论最终是「已部署待验收」还是「修复失败」，「访问环境」都要有可点击的体验链接。三层保证：`deploy.py` 部署成功即写（定时会话里不带 `--record-id` 也会从环境变量取记录）；`set-plan-status 已部署待验收` 在访问环境为空时拒绝，置「修复失败」时返回 `warning`；会话结束后定时任务按运行目录的 `deploys.jsonl` 核对，访问环境为空就补上链接并记进修复进度。

## 方案状态的流转

| 从 | 到 | 谁 |
|---|---|---|
| 已批准 | 修复中 | 定时任务认领（要求根因、方案、验收都非空） |
| 修复中 | 已部署待验收 | 会话：PR 已提、PPE 已部署（访问环境非空）、一句话解释原因已写、验收通过 |
| 修复中／已批准 | 修复失败 | 会话或定时任务：任何一步失败、会话超时或中断 |
| 修复失败 | 已批准 | RD 处理后手动改回，下一轮重试 |

`set-plan-status` 拒绝其他变化（返回退出码 3 或报错）。「待评审」「已驳回」属于 `$tutti-bug-workflow:bug-solution` 和 RD。

## 只读的字段

分析根因、根因图、修复方式、验收标准由 bug-solution 写（bug-solution 暂时屏蔽，期间由 RD 直接填写，根因图可空）；状态、修复版本、指派人由人工维护。

## 扫描条件

`feishu.py scan [--assignee 姓名] [--min-priority P1]`：指派人包含跟进人、状态为「未解决」、方案状态为「已批准」；有 `--min-priority` 时只保留该优先级及以上。按优先级、记录时间排序。
