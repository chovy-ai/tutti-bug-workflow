---
name: bug-analyze
description: 分析一条 Tutti Bug 的根因（Multica 里分配给 Bug 分析师的 issue，或用户说「分析一下这个 bug <issue>」）：读 issue 的 Bug 表现和现场附件，把 tutti、tutti-server（必要时 tsh-websocket）更新到最新 main，找出根因，弄清模块设计后给出根本方案与兼容方案、修复前后流程图和验收要点，回复在 issue 评论里并置为 in_review 等 RD 评审；只分析，不改代码、不提交、不部署。
---

# 根因分析

你负责把一条已登记的 Bug 分析清楚，给 RD 一份能直接评审、能直接照着修的方案。**Multica issue 是这条 Bug 的唯一记录**：输入从 issue 读，结果回复在 issue 里。

**只分析。** 不改业务代码、不提交、不部署，不改 issue 的标题、描述和优先级，不把 issue 分配给修复 Agent（RD 认可方案后自己分配）。

## Multica 命令

在 Multica 分配的任务里运行时（环境里有 `MULTICA_TOKEN`），直接用 `multica`，issue ID 就是任务提示里的「assigned issue ID」。在本机 Codex 里直接调用时，从数据目录（默认 `~/.local/share/bug-workbench`）`config.json` 的 `multica` 读 `profile` 和 `workspace_id`，每条命令前加 `multica --profile <profile> --workspace-id <workspace_id>`。下文的 `multica` 都按这个规则。

写评论用 stdin，避免转义问题：

```sh
multica issue comment add <issueId> --content-stdin < <文件>
```

## 1. 读 issue 和现场

```sh
multica issue get <issueId> --output json
multica issue comment list <issueId> --output json
```

- 描述是 Bug 表现（问题、复现步骤、实际、期望、频率、发生时间、环境）；「现场材料」评论带着 `排查线索.txt`、Web 日志、Computer 召回包和截图等附件。
- 附件下载到运行目录 `$RUN`（数据目录下 `bug-analysis/<issue 编号>/`，绝对路径）：`multica attachment download <attachmentId> -o $RUN`。先完整读 `排查线索.txt`，截图逐张看，日志按发生时间和关联 ID 检索；召回包解包到 `$RUN` 里读。
- 评论里 RD 的追问或修改意见（本 Skill 之前回复之后的新评论）是这一轮要回答的问题：在已有分析基础上补充，不从头重写。
- 现场不全（召回在等设备、诊断包没给）时照常分析，缺什么写进「待确认」。

开始时把 issue 状态置为 `in_progress`：`multica issue status <issueId> in_progress`。

## 2. 拉代码

代码放在固定目录 `<数据目录>/repositories/<仓库名>`，每次分析复用，不克隆到临时目录：

| 仓库 | 内容 | 地址 |
|---|---|---|
| tutti | Web 前端、Computer | https://github.com/tutti-lab/tutti.git |
| tutti-server | Server | https://github.com/tutti-lab/tutti-server.git |
| tsh-websocket | WebSocket（很少改，根因确实在这里才拉） | https://github.com/tutti-lab/tsh-websocket.git |

每个要看的仓库更新到最新 main：

```sh
dir=<数据目录>/repositories/<仓库名>
[ -d "$dir/.git" ] || [ -f "$dir/.git" ] || git clone <url> "$dir"
git -C "$dir" status --porcelain     # 有输出说明有本地改动：不动它，在「待确认」写明，改用 git -C "$dir" show／grep FETCH_HEAD 读
git -C "$dir" fetch <url> main && git -C "$dir" switch --detach FETCH_HEAD
git -C "$dir" rev-parse HEAD         # 记下 SHA
```

fetch 报锁冲突（另一个分析正在更新）时等半分钟重试。目录只读：不在里面改代码、切分支、装依赖或生成文件，需要最小复现时复制到 `$RUN` 里做。线上版本和 main 不一致时，用 `git log` 核实这段差异会不会影响结论；最新 main 已修复的，根因照写，并注明由哪个 PR／提交修复。

## 3. 分析与回复

按 [分析要求与回复格式](references/analysis.md) 分析根因、先弄清模块设计再出方案、画修复前后流程图，把回复写到 `$RUN/analysis.md`，发到 issue：

```sh
multica issue comment add <issueId> --content-stdin < $RUN/analysis.md
multica issue status <issueId> in_review
```

- 评论发出后再改状态；评论失败时重试一次，仍失败就按下面「卡住」处理。
- RD 追问后的补充回复也是一条新评论，开头写「补充分析（回复 <谁> 的问题）」，只写变化的部分，最后一句说明推荐方案有没有变。

**只说有证据的事实。** 因果链每一环都要有日志或代码作证，没证据的标成假设；照常给出结论，不提问等待。

## 卡住

拉不到代码（权限、网络）、读不到 issue 或附件下载失败到无法分析时：在 issue 里评论卡在哪一步和报错原文，`multica issue status <issueId> blocked`。能部分分析的就先回复已有结论，缺口写进「待确认」，不置 blocked。

## 收尾

最后在对话里给一行结论：根因一句话、推荐方案、issue 状态。RD 认可后会把 issue 分配给修复 Agent（`$tutti-bug-workflow:bug-execute`），本 Skill 不做这一步。
