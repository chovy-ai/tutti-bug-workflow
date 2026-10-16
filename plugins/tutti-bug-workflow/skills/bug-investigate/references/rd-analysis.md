# 交给 Room Agent 分析根因

Task 补全后（第 4 步的 `task edit` 成功、`task show` 回读无误），用 `tutti-cli task run` 把一段分析指令发到这个 Task，交给目标 Room 里的 Agent（Codex 优先，其次 Claude Code）：拉代码、分析根因、按模块设计出方案、画修复前后的流程图，结果回复在 Task 的同一个评论线程里。本 Skill 只负责把指令组织好并发出去，不等分析完成，也不自己分析。

## 选 Agent 和模型

先 Codex，其次 Claude Code。`tutti-cli agent list --room-id <roomId> --json` 里去掉 `referenceOnly` 为 `true`（历史引用）和 `availability.status` 为 `unavailable` 的，其余都是候选，按下面的顺序逐个试，第一个找得到合适模型、`task run` 被受理的就用它：

| 顺序 | Agent | 模型（`--model`） | `--reasoning-effort` |
|---|---|---|---|
| 1 | `providerId` 为 `codex` | `gpt-6.1-sol`，没有再用 `gpt-6-astra` | `high` |
| 2 | `providerId` 为 `claude-code` | Opus 5.5 | `high` |

- 能不能执行由服务端判断，目录里的 `ownership` 和 `availability` 只用来排先后，不用来排除：`ownership` 为 `self`（自己的）和 `shared`（已共享给你的）在前，`availability.status` 为 `available` 在 `checking` 前；`requestable`（目录说要先授权，`reason` 常见 `sharing_required`）排在同类最后，前面的都不行时照样试，被拒再换下一个。目录结果可能和实际共享状态不一致，不要因此跳过，也不要据此推断「当时没共享」之类的结论。
- 同一类 Agent 有多个时，在上面的先后之内：`computerId` 等于该 Room 的 `nativeComputerId`（`find_room.py` 返回的 `room.nativeComputerId`）且 `executionEnvironment` 为 `native` 的优先（在房主本机运行，能用本机的 git 登录拉私有仓库），其次同一台 Computer 的 `managed_vm`，再其次其他 Computer。所有 Codex 都试过、都没有合适模型，才轮到 Claude Code。
- 每个候选先运行 `tutti-cli agent models --room-id <roomId> --agent-target-id <id> --json`，在 `models[]` 里找模型，`--model` 传 `value` 原值（可能带连接前缀）：
  - Codex：`value` 等于或以 `gpt-6.1-sol`／`gpt-6-astra` 结尾；
  - Claude Code：`label` 或 `description` 写明 Opus 5.5，或 `value` 含 `opus-5-5`。`opus`、`opus[1m]` 这类别名只有 `label` 写的是 Opus 5.5 才算，写的是其他版本（如 Opus 4.7）不算。
- 选中的模型要支持 `high`：看 `reasoningOptionsByModel.<value>.options`，没有这一项时看 `reasoningEfforts`。
- `agent models` 报 403 等错误时跳过这个 Agent，试下一个，记下报错原文。
- 全部候选都没有合适的就不发，写进最终回复：「房间里没有可用的 Codex（gpt-6.1-sol／gpt-6-astra）或 Claude Code（Opus 5.5），未自动分析」，并逐个列出试过的 Agent、目录里的 `ownership`／`availability`（含 `reason`）和报错或拒绝原文。不换成其他模型或其他 Agent 类型。
- 向用户说明为什么没发时只陈述这些原始结果，不推断原因（如「Agent 当时没共享」「权限没生效」）；用户的说法和目录结果对不上时，两边都照写，标成待确认。

## 发出指令

按下面的模板写 `$REPORT/rd-analysis.txt`，再发：

```sh
tutti-cli task run --room-id <roomId> --task-id <taskId> --agent-target-id <agentTargetId> \
  --model <model> --reasoning-effort high \
  --instruction-file <$REPORT>/rd-analysis.txt --operation-id <新 UUID> --json
```

**要确保发送成功，发成功后就不管了。** 发送成功的标准是回执同时满足：`status` 为 `accepted`、带 `invocationId`、`taskId` 和 `agentTargetId` 是这次的 Task 和 Agent。按回执处理：

| 回执 | 怎么做 |
|---|---|
| `accepted` + `invocationId` | 发送成功，这一步结束：记下 Agent、模型、`invocationId`、`commentId`，立刻继续后面的步骤 |
| `pending`（退出码 0，执行还没受理） | 还不算成功：隔 15 秒用**同一个 `--operation-id`、同样的参数和同一份指令文件**重跑，最多 3 次。同 ID 重跑会复用那条评论、重放执行请求，不会重复触发；变成 `accepted` 就算成功。3 次后仍是 `pending`，最终回复里写「已发出，Agent 尚未受理，请在 Task 里查看」 |
| `rejected`（退出码 1，带 `rejectionCode`） | 这个组合发不出去：按上面的顺序换下一个模型或候选 Agent，用**新的** `--operation-id` 再发（被拒的结果不会改变，新 ID 会再发一条评论）。全部被拒就写进最终回复，带上每次的 `rejectionCode` 原文 |
| 超时、断网、没拿到回执 | 用同一个 `--operation-id` 和相同输入重跑一次，按新回执处理 |
| 参数错误、HTTP 错误 | 按报错修正（模型值、推理强度不被接受时换下一个模型）后用新的 `--operation-id` 再发 |

发送成功以后不再管它：不等 Agent 执行，不用 `task show` 轮询进度或回复，不读、不转述它的分析结果；最终回复里只写交给了哪个 Agent 和模型，分析结果会出现在 Task 的评论里。

- Agent 会把代码拉到它所在电脑的固定目录 `~/.local/share/bug-workbench/repositories/<仓库名>`，同一台电脑上后面的分析直接复用，只增量更新。
- 每个 Task 只发一次完整分析。QA 明确要求重新分析时再发；指令发出时缺的关键现场后来补齐时，发一次复核（见下）。

## 补齐现场后复核

指令发出时缺了 Web 日志或 Computer 召回（指令的现场线索里写了缺什么），之后补齐并挂上时（本会话自建 Task 用 `task edit`，复用已有 Task 用 `task comment --file` 追加并记录 `commentId`），Agent 可能已经按不全的现场下了结论。补齐后发一次复核，回到同一个线程：

```sh
tutti-cli task run --room-id <roomId> --task-id <taskId> --agent-target-id <同一个 Agent> \
  --reply-to <分析指令的 commentId> --model <同一个模型> --reasoning-effort high \
  --instruction-file <$REPORT>/rd-review.txt --operation-id <新 UUID> --json
```

`rd-review.txt` 只写增量，例如：

```text
现场已补齐：<补了什么，如「Computer 召回包 <文件名>（覆盖 10:50–11:05）」「Web 诊断包 <文件名>」>，已挂在 <自建 Task：描述附件；复用 Task：新增评论 commentId=<实际回执 ID> 的附件>。之前的分析是在缺这份现场时做的。请读新附件，核对上面的结论：结论不变就回复一句「复核：结论不变」并说明依据；有变化就按原来的回复格式给出更新后的完整结论，并写明哪里变了、为什么。仍然只分析，不改代码、不改 Task。
```

回执规则同上：`accepted` 带 `invocationId` 就不再管它。每批补齐的现场最多复核一次；不影响分析的补充（如 QA 改了期望的措辞、补了一张同样的截图）不发。

## 指令模板

指令要让一个没看过现场的 Agent 只读这一段就能开工：**Bug 表现** 照抄描述里 QA 的意思，**现场线索** 从 `排查线索.txt` 里挑和问题直接相关的几条（不要整份粘贴，附件 Task 上都有）。尖括号处按本次 Bug 填，没有的项删掉；其余文字原样保留。

````text
请分析这条 Bug 的根因并给出修复方案，结果直接回复在这条评论下。这一轮只分析：不改业务代码、不提交、不部署，不改 Task 的状态、标题、描述和附件。

【Bug 表现】
问题：<1–3 句：在哪个页面、做了什么、看到了什么、哪里不对；界面报错原文照抄>
复现步骤：
1. <……>
2. <……>
实际：<……>
期望：<……>
频率：<必现／偶现（约 x 次中 y 次）／出现 1 次>
发生时间：<2026-10-13 20:52>（北京时间）
环境：<生产／PPE 泳道名> · <Mac／Windows／Web> · <Agent 名称>
页面链接：<出问题页面的完整 URL>

【现场线索】
- <时间> <来源：Web／Computer> <报错原文或关键字段>（request id：<id>）
- <时间> <method 路径> → <状态码>（request id：<id>）
- 关联 ID：账号 <userId>，房间 <roomId>，会话 <sessionId>，Computer <computerId>，Agent <agentTargetId>
- 版本：Web <页面版本>，Computer <computerVersion>
- 现场位置：<本会话自建 Task 的描述附件；复用 Task 的现场评论 commentId=<实际回执 ID>，包括后到现场的评论 ID>。
- Task 附件：<截图文件名>、排查线索.txt（完整的日志核对、关联 ID 和环境）、<web-logs.log 或诊断包>、<Computer 召回包>。能读到附件就先完整读，截图逐张看；读不到就以上面的线索为准，并在回复的「待确认」里说明。
- 服务端日志没有拉，需要时按上面的 request id 查 tutti-server 日志；查不到就标成待确认，不要停下。

【怎么做】
1. 拉代码。代码放在固定目录 ~/.local/share/bug-workbench/repositories/<仓库名>，以后每次分析都复用这里，不要克隆到临时目录：
   - tutti（Web 前端、Computer）：https://github.com/tutti-lab/tutti.git
   - tutti-server（Server）：https://github.com/tutti-lab/tutti-server.git
   - tsh-websocket（WebSocket，很少改，根因确实在这里才拉）：https://github.com/tutti-lab/tsh-websocket.git
   每个要看的仓库这样更新到最新 main（<url> 和 <仓库名> 换成上面的值）：
     dir=~/.local/share/bug-workbench/repositories/<仓库名>
     [ -d "$dir/.git" ] || [ -f "$dir/.git" ] || git clone <url> "$dir"
     git -C "$dir" status --porcelain     # 有输出说明有本地改动：不要动它，在回复的「待确认」里写明，改用 git -C "$dir" show／grep FETCH_HEAD 读
     git -C "$dir" fetch <url> main && git -C "$dir" switch --detach FETCH_HEAD
     git -C "$dir" rev-parse HEAD         # 记下 SHA
   fetch 报锁冲突（另一个分析正在更新）时等半分钟重试。目录只读：不在里面改代码、切分支、装依赖或生成文件，需要跑最小复现时复制到临时目录做。
   线上版本和 main 不一致时，用 git log 核实这段差异会不会影响结论；最新 main 已修复的，根因照写，并注明由哪个 PR／提交修复。

2. 分析根因。从现场出发：按发生时间和关联 ID 在日志里找到出错的那几条，排出时间线，再在代码里找到对应实现，解释为什么会这样。因果链每一环都要有日志或代码作证，没证据的标成假设；现场不够就写进「待确认」，照常给出结论，不要提问等待。

3. 先弄清模块设计，再出方案。动手设计方案前，先把这个功能所在模块的整体设计弄清楚：涉及哪些端和组件、各自负责什么、数据和状态怎么流转、现有的约定和抽象是什么、同类问题在模块里别处是怎么处理的。方案要顺着这套设计来，复用已有的机制和约定，不另起一套，不在调用点打补丁绕过；如果问题恰恰出在设计本身，直接指出来，并说明顺着现有设计修和调整设计各自的代价。
   给出两个方案并比较：
   - 根本方案：从根上消除原因；
   - 兼容方案：改动更小、风险更低的做法。
   比较覆盖范围、对模块设计的影响、兼容性、改动成本、回归风险和回滚方式，最后给出推荐。两个方案相同时说明原因。

4. 画修复前后的工作流程图。用 Mermaid sequenceDiagram 画两张，按端分泳道（用户／Web 前端／Server／WebSocket／Computer／数据库，用到哪个画哪个）：
   - 修复前：现在的实际流程，出错的那一段用 rect rgb(253, 226, 225) 包起来，Note 写「❌ 根因：……」；
   - 修复后：推荐方案落地后的流程，改动的那一段用 rect rgb(230, 244, 234) 包起来，Note 写「✅ 修复：……」。
   两张图的参与方和前后步骤对得上，只有改动的部分不同。文字用大白话，不写类名、函数名、错误码常量；每张不超过 10 步，每个框和箭头不超过 20 个字；一端内部的动作用 Note，不画自己指向自己的箭头。

【回复格式】
按下面的顺序写，开头三段让人只看它们就明白发生了什么：

根因：两三句大白话，150 字以内：哪个环节、在什么条件下、做错了什么，导致用户看到什么。不堆术语、不贴 ID。
复现路径：前置条件和操作步骤，到出现问题的那一步。
预期工作流程：正常应该怎么走（每一步由哪一端做什么），并指出实际在第几步偏离。

模块现状：这个功能涉及的组件和职责、数据／状态流转、相关的现有约定（几行即可）。
修复方案：根本方案与兼容方案（做法、改动、兼容性与风险、回滚）、取舍、推荐方案及理由。
修改范围：按仓库列出要改的文件或模块和实现要点，以及要补的测试。
修复前流程图：Mermaid 代码块。
修复后流程图：Mermaid 代码块。
验收要点：修复前怎么复现；修复后要验证的用例（原问题、边界、回归）。
证据：时间线、日志（附件名、时间、request id、关键内容）、代码位置（仓库@sha 路径:行号）。
影响范围：哪些端、场景、用户会遇到；是否影响数据。
待确认：还没证实的假设，以及怎么验证。
分析依据：tutti@<sha>，tutti-server@<sha>，tsh-websocket@<sha>（没看的仓库不写）。
````
