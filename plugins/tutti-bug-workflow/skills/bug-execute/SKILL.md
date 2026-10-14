---
name: bug-execute
description: 修复 Room 里的一条 Bug Task 并部署 PPE（RD 手动触发，如「修复这个 Task <链接>」「按根本方案修一下这个 bug」）：用 tutti-cli 读 Task 的 Bug 表现，按 RD 认可的方案（通常是 Room Agent 在 Task 评论里给的根因分析）从远端分支切出 worktree 修复、提 PR 到 main，部署 PPE（server 泳道 → ws 泳道 → 前端预览，涉及 Computer 发分支 canary）后移除 worktree，按验收要点自验证，最后把原因、PR、体验链接和验证结果回复到 Task；也用于销毁某条 Bug 的 PPE 泳道。
---

# 修复与部署

你负责把一条 Bug Task 的修复方案落成代码，部署到 PPE 并验证，结果回复到这个 Task。

**由 RD 手动触发，一次一条 Task。** 没有定时任务，也不扫描 Bug 列表。Task 是唯一的对外记录：修复完成或失败，都要回复到 Task 的评论里。脚本路径相对本 Skill 目录（`skills/bug-execute/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup`（「修复与部署」场景）负责。

**修复部署后，体验环境必须写进 Task 回复。** 只要有任何一端部署成功，不论最后成功还是失败，回复里都要有一个点开就能体验修复的链接：前端预览链接（指向这条 Bug 的 Server 泳道）；只改了 Computer 时是 canary 发布页。RD 和 QA 靠它去体验修复，漏写等于没交付。

**只说有证据的事实。** 回复和对话里的每条结论都要有代码、测试输出、部署结果或截图作证；没证实的写成「待确认」。

## 1. 确定 Task 和方案

1. **Task**：从用户消息里取 Room ID 和 Task ID（Task 链接里通常两个都有）。只有 Task ID 时问用户是哪个房间（可给房间名，用 `tutti-cli room list --all --json` 找）。然后读 Task：
   ```sh
   tutti-cli task show --room-id <roomId> --task-id <taskId> --json
   ```
   读不到（403、不存在、未登录）就停下，告诉用户原因；未登录时后台运行 `tutti-cli login`，用户在浏览器登录后重试。
2. **方案**：`tutti-cli` 读不到 Task 的评论，所以方案以用户在对话里给的为准，通常是 Room Agent 在 Task 里回复的根因分析（根因、根本方案／兼容方案、修改范围、验收要点）。用户只说「按根本方案修」却没贴分析内容时，**请用户把那条分析回复贴过来**（或直接说明要怎么改），拿到之前不动代码。
3. 把 Task 的描述、附件清单和方案整理成运行目录里的 `context.md`。运行目录：数据目录（默认 `~/.local/share/bug-workbench`）下的 `bug-fixes/<taskId>/`。
4. 固定这条 Bug 的分支和泳道：
   ```sh
   python3 scripts/deploy.py fix-names --task-id <taskId>
   ```
   返回 `branch`（`codex/bug-<Task ID 前 8 位>`）和 `lane`（`ppe-bug-<同样 8 位>`）。同一条 Task 每次修复都用这两个名字，重试时接着原分支。

方案和最新 main 的代码对不上（已被修复、根因不成立）或修复必须超出方案范围时，先停下来和用户说明，不自行扩大范围。

## 2. 从远端分支切出 worktree

每个要改的仓库（worktree 从远端最新 main 切出；远端已有这条 Bug 的修复分支时从它切出，接着上次的改动）：tutti（Web、Computer）、tutti-server（Server）、tsh-websocket（WebSocket，基础设施，方案没要求就不改）。

```sh
python3 scripts/repos.py start --repo tutti --branch codex/bug-<短 ID>
```

返回 `resumed: true` 表示接着上一次的分支；`behind_main` 大于 0 时先 `git rebase origin/main`（冲突解决不了就判失败）。详见 [修复工作区](references/code.md)。

## 3. 修复

读 worktree 里的 AGENTS.md 和开发说明，按方案范围修改，保持现有架构与风格；补测试，跑相关测试、类型检查、lint，直到通过。

## 4. 提交、推送、提 PR

```sh
git -C <worktree> add -A && git -C <worktree> commit -m "fix: <摘要>（task <短 ID>）"
python3 scripts/repos.py push --path <worktree>     # 推送分支，worktree 保留到部署完
gh pr create -R tutti-lab/<repo> --base main --head codex/bug-<短 ID> --title "fix: …" --body "…"
```

分支已有打开的 PR（`gh pr view -R … codex/bug-<短 ID>`）就复用，不重复创建。PR 描述写 Task（Room ID、Task ID、标题）、根因一句话、改动、测试结果、PPE 部署信息（部署后用 `gh pr comment` 补上）。

## 5. 部署 PPE

顺序固定，前一步失败就不做后一步，详见 [PPE 部署](references/deploy.md)。每条命令返回 run 链接和结论；成功的 web／computer 部署带 `access_url`（体验链接）。

- 改了 tutti-server：`python3 scripts/deploy.py server --branch codex/bug-<短 ID> --lane <lane>`，等它成功。
- 改了 tsh-websocket（只在方案明确要求时修改，没改就跳过）：`python3 scripts/deploy.py websocket --branch codex/bug-<短 ID> --lane <lane>`。新泳道缺 WebSocket V2 基础设施会失败（看 `failed_log_tail` 和 `hint`）：其他端照常部署，最后判失败，写明需要人工先建 ws 基础设施。
- 改了前端（或改了 server，前端需要对接这个泳道）：`python3 scripts/deploy.py web --branch <tutti 分支> --server-lane <lane>`。只改了 server 时，用 `main` 作为前端分支部署预览并指向泳道。
- 改了 Computer（desktopd、runtime 等）：`python3 scripts/deploy.py computer --branch codex/bug-<短 ID>`，记下 canary 版本。
- 泳道部署时关闭了连接器授权。修复依赖连接器授权才能验证时，PR 照提、部署照做，然后判失败，说明「新泳道需要人工预配 connector task-platform binding 后重试」。

## 6. 移除 worktree

PPE 部署结束（成功或失败）后，移除这次的每个 worktree：

```sh
python3 scripts/repos.py remove --path <worktree>
```

分支已推送、PR 已提，worktree 不再需要；有未推送的改动时它会拒绝，先推送（或确认放弃后加 `--discard`）。中途失败结束时也要移除，不留下本地工作区。

## 7. 自验证

部署成功后自己按方案里的验收要点逐条验证，完整流程见 [部署后自验证](references/verify.md)：用 `chrome-devtools` MCP 连接本机 Chrome（用它的 tutti.sh 登录态），只操作自己新开的标签页；涉及 UI 的用例每条都要截图，存到运行目录。任何必需用例失败，或涉及 UI 却没能截图（Chrome 不可用、未登录）→ 判失败。

## 8. 回复到 Task

先写「一句话原因」：`gh pr diff` 看这次 PR 实际改了什么，用一句话告诉 QA 和产品这个 Bug 为什么会出现。讲原因不讲改法，不用类名、函数名、接口名、错误码；单行、最好 50 字以内；实际修的和方案里的根因不一样时，按 PR 写。例：「切换房间时顶部标题没跟着刷新，一直显示上一个房间的名字」。

按 [验证模板](assets/verification.md) 写 `$RUN/reply.txt`，发到 Task：

```sh
tutti-cli task comment --room-id <roomId> --task-id <taskId> --content-file <$RUN>/reply.txt \
  --operation-id <新 UUID> --json
```

- 回执 `status: posted` 才算发出；超时或没拿到回执时用同一个 `--operation-id` 和同一份文件重试一次。
- 只发评论，不带 `--agent-target-id`，不触发任何 Agent；不改 Task 的标题、描述和附件（`task edit` 带附件会整段替换描述，可能弄丢 QA 的附件）。
- 截图留在运行目录，回复里写文件名和本机路径；评论不能带附件。
- **失败时也要回复**：写清卡在哪一步、错误信息和链接，已部署成功的一端照样给出体验链接。

最后在对话里给用户一行结论：一句话原因、PR、体验链接、验证结果，以及 Task 回复是否已发出。

## 泳道回收

泳道不自动销毁。用户要求销毁某条 Bug 的泳道时：

```sh
python3 scripts/deploy.py fix-names --task-id <taskId>
python3 scripts/deploy.py destroy-lane --lane ppe-bug-<短 ID>                      # server
python3 scripts/deploy.py destroy-lane --lane ppe-bug-<短 ID> --service websocket  # 部署过 ws 时
```

销毁后在 Task 里回复一句「已销毁 PPE 泳道 ppe-bug-<短 ID>：<run 链接>」。
