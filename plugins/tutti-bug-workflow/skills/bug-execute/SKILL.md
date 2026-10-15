---
name: bug-execute
description: 修复 Multica 里的一条 Tutti Bug issue 并部署 PPE（RD 认可分析方案后把 issue 分配给 Bug 解决 Agent，或手动说「修复这个 issue <编号>」）：读 issue 的 Bug 表现、现场和分析 Agent 的根因方案及 RD 的评审意见，从远端基线分支（默认 main）切出 worktree 修复、提 PR 到基线，基线上已修好时直接部署，部署 PPE（server 泳道 → ws 泳道 → 前端预览，涉及 Computer 发分支 canary）后移除 worktree，按验收要点自验证，最后把原因、PR、体验链接、验证结果和截图回复到 issue；也用于销毁某条 Bug 的 PPE 泳道。
---

# 修复与部署

你负责把一条 Bug 的修复方案落成代码，部署到 PPE 并验证，结果回复到这条 Bug 的 Multica issue。

**由 RD 触发，一次一条 issue。** RD 评审分析方案后把 issue 分配给你（Multica 会让你立刻开始），或在本机 Codex 里手动让你修；不扫描 Bug 列表。**Multica issue 是唯一的对外记录**：修复完成或失败，都要回复到 issue 的评论里。脚本路径相对本 Skill 目录（`skills/bug-execute/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup`（「修复与部署」场景）负责。

**Multica 命令。** 在 Multica 分配的任务里运行时（环境里有 `MULTICA_TOKEN`），直接用 `multica`，issue ID 就是任务提示里的「assigned issue ID」。在本机 Codex 里直接调用时，从数据目录（默认 `~/.local/share/bug-workbench`）`config.json` 的 `multica` 读 `profile` 和 `workspace_id`，每条命令前加 `multica --profile <profile> --workspace-id <workspace_id>`。下文的 `multica` 都按这个规则。

**修复部署后，体验环境必须写进 issue 回复。** 只要有任何一端部署成功，不论最后成功还是失败，回复里都要有一个点开就能体验修复的链接：前端预览链接（指向这条 Bug 的 Server 泳道）；只改了 Computer 时是 canary 发布页。RD 和 QA 靠它去体验修复，漏写等于没交付。

**只说有证据的事实。** 回复和对话里的每条结论都要有代码、测试输出、部署结果或截图作证；没证实的写成「待确认」。

## 1. 确定 issue 和方案

1. **issue**：Multica 分配给你的 issue，或用户给的编号（如 `TES-123`）／链接。读 issue 和全部评论：
   ```sh
   multica issue get <issueId> --output json
   multica issue comment list <issueId> --output json
   ```
   读不到（不存在、未登录）就停下，告诉用户原因。记下 `identifier`（如 `TES-123`），开始时把状态置为 `in_progress`：`multica issue status <issueId> in_progress`。
2. **方案**：以 issue 评论里分析 Agent 的根因分析为准（根因、根本方案／兼容方案、修改范围、验收要点），再叠加 RD 在它之后的评审评论。**RD 把 issue 分配给你就表示认可分析里的推荐方案**；评论里指定了另一个方案或提了修改意见时以评论为准，多条意见冲突时以最新的为准。issue 里还没有分析结论、或 RD 的意见不足以确定改法时，不动代码：在 issue 里评论缺什么，`multica issue status <issueId> blocked`，结束。
3. 附件（「现场材料」评论里的排查线索、日志，截图）按需用 `multica attachment download <attachmentId> -o $RUN` 下载。把 issue 的描述、方案和 RD 意见整理成运行目录里的 `context.md`。运行目录（`$RUN`）：数据目录下的 `bug-fixes/<issue 编号>/`。
4. 固定这条 Bug 的分支和泳道：
   ```sh
   python3 scripts/deploy.py fix-names --issue <issue 编号>
   ```
   返回 `branch`（`codex/bug-<编号小写>`，如 `codex/bug-tes-123`）和 `lane`（`ppe-bug-<同样>`）。同一条 issue 每次修复都用这两个名字，重试时接着原分支。
5. **基线分支**：默认 `main`。Bug 出在还没合并的功能分支上（分析或 RD 评论指定了分支，或问题代码只在某个打开的 PR 里）时，以那个分支为基线：从它切 worktree，PR 也提到它。RD 在评论里指定的基线优先；需要问 RD 才能确定时，评论问清楚后置 `blocked`。

拿方案和基线最新代码核对：

- **基线上已经修好**（问题代码已改掉，比如修复已经合进基线）：不改代码、不提 PR，**照常部署 PPE**（用基线分支部署第 5 步涉及的各端），按第 7 步自验证，按第 8 步回复，正文写明「基线 <分支>@<SHA> 已包含修复 <提交／PR 链接>，本次未改代码，直接部署验证」。
- **根因不成立**，或修复必须超出方案范围：先停下来，在 issue 里评论说明，置为 `blocked`，不自行扩大范围。

## 2. 从远端分支切出 worktree

每个要改的仓库（worktree 从远端最新基线切出；远端已有这条 Bug 的修复分支时从它切出，接着上次的改动）：tutti（Web、Computer）、tutti-server（Server）、tsh-websocket（WebSocket，基础设施，方案没要求就不改）。

```sh
python3 scripts/repos.py start --repo tutti --branch <branch> [--base <基线分支>]   # 基线是 main 时不传
```

返回 `resumed: true` 表示接着上一次的分支；`behind_main`（落后基线的提交数）大于 0 时先 `git rebase origin/<基线分支>`（冲突解决不了就判失败）。详见 [修复工作区](references/code.md)。

## 3. 修复

读 worktree 里的 AGENTS.md 和开发说明，按方案范围修改，保持现有架构与风格；补测试，跑相关测试、类型检查、lint，直到通过。

## 4. 提交、推送、提 PR

```sh
git -C <worktree> add -A && git -C <worktree> commit -m "fix: <摘要>（<issue 编号>）"
python3 scripts/repos.py push --path <worktree>     # 推送分支，worktree 保留到部署完
gh pr create -R tutti-lab/<repo> --base <基线分支> --head <branch> --title "fix: …" --body "…"
```

分支已有打开的 PR（`gh pr view -R … <branch>`）就复用，不重复创建。PR 描述写 issue（编号、标题、链接）、根因一句话、改动、测试结果、PPE 部署信息（部署后用 `gh pr comment` 补上）。

## 5. 部署 PPE

顺序固定，前一步失败就不做后一步，详见 [PPE 部署](references/deploy.md)。每条命令返回 run 链接和结论；成功的 web／computer 部署带 `access_url`（体验链接）。

- 改了 tutti-server：`python3 scripts/deploy.py server --branch <branch> --lane <lane>`，等它成功。
- 改了 tsh-websocket（只在方案明确要求时修改，没改就跳过）：`python3 scripts/deploy.py websocket --branch <branch> --lane <lane>`。新泳道缺 WebSocket V2 基础设施会失败（看 `failed_log_tail` 和 `hint`）：其他端照常部署，最后判失败，写明需要人工先建 ws 基础设施。
- 改了前端（或改了 server，前端需要对接这个泳道）：`python3 scripts/deploy.py web --branch <tutti 分支> --server-lane <lane>`。只改了 server 时，用基线分支作为前端分支部署预览并指向泳道；基线上已修好、本次没改代码时，用基线分支部署。
- 改了 Computer（desktopd、runtime 等）：`python3 scripts/deploy.py computer --branch <branch>`，记下 canary 版本。
- 泳道部署时关闭了连接器授权。修复依赖连接器授权才能验证时，PR 照提、部署照做，然后判失败，说明「新泳道需要人工预配 connector task-platform binding 后重试」。

## 6. 移除 worktree

PPE 部署结束（成功或失败）后，移除这次的每个 worktree：

```sh
python3 scripts/repos.py remove --path <worktree>
```

分支已推送、PR 已提，worktree 不再需要；有未推送的改动时它会拒绝，先推送（或确认放弃后加 `--discard`）。中途失败结束时也要移除，不留下本地工作区。

## 7. 自验证

部署成功后自己按方案里的验收要点逐条验证，完整流程见 [部署后自验证](references/verify.md)：用 `chrome-devtools` MCP 连接本机 Chrome（用它的 tutti.sh 登录态），只操作自己新开的标签页；涉及 UI 的用例每条都要截图，存到运行目录，回复时作为评论附件上传。任何必需用例失败，或涉及 UI 却没能截图（Chrome 不可用、未登录）→ 判失败。

## 8. 回复到 issue

先写「一句话原因」：`gh pr diff` 看这次 PR 实际改了什么，用一句话告诉 QA 和产品这个 Bug 为什么会出现。讲原因不讲改法，不用类名、函数名、接口名、错误码；单行、最好 50 字以内；实际修的和方案里的根因不一样时，按 PR 写。例：「切换房间时顶部标题没跟着刷新，一直显示上一个房间的名字」。

按 [验证模板](assets/verification.md) 写 `$RUN/reply.md`，连同这次的全部截图（`fix-*`、`before-*`）作为附件发到 issue，再改状态：

```sh
multica issue comment add <issueId> --content-stdin --allow-external-file \
  --attachment <$RUN>/fix-<编号小写>-1-<时间>.png --attachment <$RUN>/before-<编号小写>-1-<时间>.png < <$RUN>/reply.md
multica issue status <issueId> in_review     # 已部署待验收；修复失败时用 blocked
```

- 每张截图一个 `--attachment`，附件显示的就是文件名，回复正文按文件名引用，不写本机路径。`$RUN` 不在工作目录里，必须带 `--allow-external-file`，否则 CLI 拒绝读取。
- 附件上传失败时评论不会发出：按报错修正（文件名重复、空文件、文件过大）后重发。结果不确定时先 `multica issue comment list` 回读，确实没发出再重发，不重复发评论。
- 只发评论、改状态，不改 issue 的标题、描述和优先级，不把 issue 分配给别人；验收通过后由 QA 置为 `done`。
- **失败时也要回复**：写清卡在哪一步、错误信息和链接，已部署成功的一端照样给出体验链接，状态置为 `blocked`。

最后在对话里给用户一行结论：一句话原因、PR、体验链接、验证结果，以及 issue 回复是否已发出、当前状态。

## 泳道回收

泳道不自动销毁。用户要求销毁某条 Bug 的泳道时：

```sh
python3 scripts/deploy.py fix-names --issue <issue 编号>
python3 scripts/deploy.py destroy-lane --lane <lane>                      # server
python3 scripts/deploy.py destroy-lane --lane <lane> --service websocket  # 部署过 ws 时
```

销毁后在 issue 里回复一句「已销毁 PPE 泳道 <lane>：<run 链接>」。
