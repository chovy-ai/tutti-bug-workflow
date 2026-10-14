# 交给 Room Agent 分析根因

Task 补全后（第 4 步的 `task edit` 成功、`task show` 回读无误），用 `tutti-cli task run` 把一段分析指令发到这个 Task，交给目标 Room 里的 Codex Agent：拉代码、分析根因、按模块设计出方案、画修复前后的流程图，结果回复在 Task 的同一个评论线程里。本 Skill 只负责把指令组织好并发出去，不等分析完成，也不自己分析。

## 选 Agent 和模型

1. `tutti-cli agent list --room-id <roomId> --json`，只看 `providerId` 是 `codex`、`availability.status` 是 `available`、`referenceOnly` 为 `false` 的 Agent。按下面的顺序排候选：
   1. `computerId` 等于该 Room 的 `nativeComputerId`（`find_room.py` 返回的 `room.nativeComputerId`），且 `executionEnvironment` 是 `native`：在房主本机运行，能用本机的 git 登录拉私有仓库；
   2. 同一台 Computer 的 `managed_vm`；
   3. 其他 Computer 上的 Codex。
2. 对第一个候选运行 `tutti-cli agent models --room-id <roomId> --agent-target-id <id> --json`，在 `models[].value` 里按顺序找（值可能带连接前缀，按结尾匹配，传给 `--model` 时用原值）：
   1. `gpt-6.1-sol`，`--reasoning-effort high`；
   2. 没有时用 `gpt-6-astra`，`--reasoning-effort high`。

   `reasoningOptionsByModel.<model>.options` 里要有 `high`。两个都没有，换下一个候选 Agent；全部候选都没有就不发，写进最终回复（「房间里没有可用的 Codex Agent 或模型，未自动分析」）。不换成其他模型或其他 Agent 类型。
3. `agent models` 报 403 等错误时跳过这个 Agent，试下一个。

## 发出指令

按下面的模板写 `$REPORT/rd-analysis.txt`，再发：

```sh
tutti-cli task run --room-id <roomId> --task-id <taskId> --agent-target-id <agentTargetId> \
  --model <model> --reasoning-effort high \
  --instruction-file <$REPORT>/rd-analysis.txt --operation-id <新 UUID> --json
```

- 回执是 `accepted` 或 `pending` 就算发出，不等 Agent 执行完；`rejected`（退出码 1）时换下一个模型或候选 Agent 再发一次，都被拒就写进最终回复，带上拒绝原因。
- 结果不确定（超时、断网）时先 `task show` 看评论里是否已有这条指令，确实没有再用同一个 `--operation-id` 重发。
- 每个 Task 只发一次。QA 之后补充现场、再 `task edit` 时不重发；QA 明确要求重新分析时再发。

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
- Task 附件：<截图文件名>、排查线索.txt（完整的日志核对、关联 ID 和环境）、<web-logs.log 或诊断包>、<Computer 召回包>。能读到附件就先完整读，截图逐张看；读不到就以上面的线索为准，并在回复的「待确认」里说明。
- 服务端日志没有拉，需要时按上面的 request id 查 tutti-server 日志；查不到就标成待确认，不要停下。

【怎么做】
1. 拉代码。涉及的仓库：tutti（Web 前端、Computer）、tutti-server（Server）、tsh-websocket（WebSocket，很少改，根因确实在这里才看）。本机已有检出就 git fetch 后在 origin/main 上读，没有就克隆最新 main 到临时目录；只读，不在检出里改代码、切分支或装依赖。记下每个仓库的 commit SHA。线上版本和 main 不一致时，用 git log 核实这段差异会不会影响结论；最新 main 已修复的，根因照写，并注明由哪个 PR／提交修复。

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
