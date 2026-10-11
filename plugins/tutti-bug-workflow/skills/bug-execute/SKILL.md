---
name: bug-execute
description: 执行 RD 已批准的 Bug 修复方案：校验飞书 Bug 管理表记录里的批准，从远端最新 main 切出 worktree 修复，跑检查、推送分支并提 PR 后解除 worktree，按验收标准验证，把验证结果和 PR 回填到同一条记录。
---

# 修复与验证

你负责把 `$tutti-bug-workflow:bug-solution` 中 RD 已批准的方案落成代码，并证明修复后的行为符合验收标准。

**无状态。** 飞书 Bug 管理表里的记录是唯一事实来源，不建本地档案。`record_id` 记在会话上下文里；截图、测试输出等放在会话临时目录（下称 `$TMP`）。脚本路径相对本 Skill 目录（`skills/bug-execute/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责。

**不改状态。** 「状态」「修复版本」由人工操作。本 Skill 只写「验证结果」「关联 PR」，并把证据上传到「截图、视频、日志」；分析根因、修复方式、验收标准只读。字段细节见 [字段规则](references/fields.md)。

## 1. 校验批准

```sh
python3 scripts/feishu.py check-approval --record-id REC
```

- 通过（`approved: true`）时返回批准人、原话，以及已批准的根因、方案和验收标准，后面以这份内容为准。
- 不通过时（缺批准、批准后内容被改、字段为空）停下，把 `problems` 告诉用户，回到 `$tutti-bug-workflow:bug-solution` 让 RD 批准；不在未批准的方案上改代码。

## 2. 切出 worktree

每个要改的仓库各切一个，分支名 `codex/<bug-摘要>`（小写英文和连字符）：

```sh
python3 scripts/repos.py start --repo tutti --branch codex/room-name-sync
```

脚本先 fetch 远端 main，再在数据目录的 `worktrees/<仓库>/<分支>` 下从最新 main 建 worktree 和新分支，返回 `worktree` 路径和 `base_sha`。分支已存在（本地或远端）时报错，换个名字。所有改动都在这个 worktree 里做。详见 [修复工作区](references/code.md)。

## 3. 修复

1. 读 worktree 里的 AGENTS.md、开发说明和相关实现，核对方案里的代码位置在最新 main 上仍成立。main 已有变化导致方案不适用时停下，回到 bug-solution。
2. 按批准的范围修改，保持现有架构与风格；需要超出范围的改动先和 RD 确认（实质变化需要重新批准）。
3. 补或改测试，跑与改动相关的测试、类型检查、lint。失败就修，修不好如实记录。
4. 提交，提交信息说明修了什么、对应哪条 Bug。

## 4. 推送、提 PR、解除 worktree

```sh
python3 scripts/repos.py finish --path <worktree>
gh pr create --repo tutti-lab/tutti --base main --head codex/room-name-sync --title "fix: …" --body "…"
python3 scripts/feishu.py add-pr --record-id REC --url <PR 链接>
```

- `finish` 要求工作区干净且有新提交，推送分支并核对远端已指向本地 HEAD，然后删除 worktree 和本地分支，返回 `pushed_sha`。推送失败时 worktree 保留，修好再跑。
- PR 描述写：Bug 记录链接、根因一句话、改动、测试结果、验收方式。
- 放弃修复时用 `python3 scripts/repos.py remove --path <worktree>`；有未推送的提交需加 `--discard` 才会丢弃。

## 5. 验证

按「验收标准」逐条执行，浏览器验收复用当前可用的 Playwright、浏览器 MCP 或宿主浏览器工具。环境与版本核对见 [验证环境](references/validation.md)。

- 先确认验证环境部署的版本包含 `pushed_sha`；确认不了记为 `blocked`，不能拿未部署修复的环境的结果当作通过。
- 每条用例记录：步骤、断言、实际结果、`passed`／`failed`／`not_run`／`blocked`、证据（截图、日志、测试输出）。
- 截图等证据上传：`python3 scripts/feishu.py attach --record-id REC --file $TMP/after-fix-1.png`。

## 6. 回填与回复

按 [验证模板](assets/verification.md) 写「验证结果」：

```sh
python3 scripts/feishu.py write --record-id REC --set verification=@$TMP/verification.md
```

失败或阻塞也要写，写清原因和下一步。回复：飞书记录链接、PR、改动摘要、验证结果、未覆盖的风险；状态由人工流转，不在回复里声称已验收。
