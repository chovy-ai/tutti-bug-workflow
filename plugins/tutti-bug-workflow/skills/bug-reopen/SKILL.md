---
name: bug-reopen
description: 把一条已有的 Bug Task 打回（QA 发来已有 Task 的链接，配上截图或一句「这里还有问题」「没修好」「打回去」「验收不通过」「退回待办」等都算，不需要说固定的词；在提 Bug 的同一个会话里说「之前提的 bug 还有问题」「给它加个评论打回去」、不带链接也算，Task 从会话上下文里取）：用全局安装的 `tutti-cli`（账号登录版）读出原 Task，和提 Bug 一样固定采集这一轮的现场日志（Web 页面日志、Computer 日志），记下相关请求的 request id，在原 Task 下发一条评论写清这一轮的表现，截图、排查线索文件和全部日志作为评论附件挂上，用 `task status` 把 Task 改回待办（todo），再默认用 `task run` 在这条评论的线程里交给该 Room 的 Agent 重新分析（Codex 优先，其次 Claude Code，推理强度 high）；不新建 Task、不改原描述和附件，自己不分析根因，只有遇到自己无法解决的卡点才向用户提问。
---

# 验收不通过，打回 Task

你负责把一次验收失败变成原 Task 下一条**上下文完整**的打回评论，把 Task 改回待办交还给 RD，再把重新分析交给 Room 里的 Agent：读原 Task、采集这一轮的全部现场、发评论挂上现场、改状态、发分析指令。**自己不分析根因，不读代码。**

**什么时候用本 Skill。** QA 指向一条**已有 Task**，并且说这个问题还在：配一张截图、一句「这里还有问题」「打回去」就够，不需要说「验收不通过」。指向已有 Task 有两种方式：

- 发 Task 链接（带 `task=<taskId>`）；
- 在提 Bug 的同一个会话里说「之前提的 bug」「刚才那个 bug」，不带链接：Task 就是本会话前面建好或复用的那条（见第 1 步）。

同一个会话里、Task 还没修过（`task show` 的状态是 `todo` 或 `in_progress`）、QA 只是补充现场或说明时，那是提 Bug 的补充，继续按 `$tutti-bug-workflow:bug-investigate` 第 5 步按 Task 来源更新：本会话自建且保留全部附件时更新描述，复用已有 Task 时追加评论；Task 已经修过（状态是 `in_review` 或 `done`），或 QA 明确说修过了还在、要打回时，才用本 Skill。QA 要记的是一个新问题时，用 `$tutti-bug-workflow:bug-investigate` 提 Bug；拿不准是同一个问题还是新问题时，先问 QA 一句。

**用全局安装的 `tutti-cli` 读写 Task。** 它是 npm 包 `@tutti-os/tutti-cli`（Node.js 24+），以本机 `tutti-cli login` 登录的 Tutti 账号直接调用 Tutti 服务，在 QA 本机的 Codex／Claude Code 里就能跑；权限按这个账号在目标 Room 的成员身份判断。开始前运行 `tutti-cli --help` 和 `tutti-cli whoami --json`：

- `--help` 里没有 `login`：没装，或 PATH 里先找到的是 Computer 自带的 Agent 版 `tutti-cli`（它的 `task status` 只能改 Agent 自己的 Task，不能用）。改用 `"$(npm prefix -g)/bin/tutti-cli"`；仍没有就按 `$tutti-bug-workflow:bug-setup`（「QA 提 Bug」场景）安装。确认可用的那个路径记为 `TUTTI_CLI`（如 `export TUTTI_CLI="$(npm prefix -g)/bin/tutti-cli"`），本 Skill 里所有 `tutti-cli` 命令都用它，不再依赖 PATH 里排在前面的那个。
- `--help` 里没有 `tutti-cli task status`：版本过旧（0.1.3 起才有），按 `$tutti-bug-workflow:bug-setup` 升级到最新版，不改用别的方式改状态。
- `whoami` 报未登录或会话失效：按下面「登录过期」自动恢复。

本 Skill 用到的命令：`task show`（读 Task）、`task comment`（发打回评论，带附件）、`task status`（改回待办）、`agent list`／`agent models`／`task run`（交给 Room Agent 重新分析），每条都要显式带 `--room-id`。`tutti-cli` 读不到 Task 的评论，也列不出 Task。

**一旦调用就走完全程。** 每次打回都执行第 1–7 步：发评论、改状态、交给 Agent 重新分析缺一不可，不能只发评论或只改状态就结束。只有 QA 明确说「不用分析」「只打回」时跳过第 6 步。

**连续执行，一次做完。**

- 每一步做完立刻开始下一步，中途不输出阶段总结，不问「要不要继续」「要不要采集日志」。
- 耗时操作在本轮内等它完成：Computer 远端召回最长约 25 分钟，期间并行做其他步骤，不把控制权交还给用户。
- 某一项卡住时记下原因，继续其他能做的；全部做完或全部卡住才写最终回复。

**尽量并行。** Web 日志先采（它给出失败请求的 request id 和 Computer 线索），随后 Computer 召回用后台进程跑，主 agent 同时读 Task、写评论。

**不查服务端日志。** Web 和 Computer 日志里的请求都带网关的 request id（`x-zk-request-id`），只把相关请求和它们的 request id 记进排查线索，RD 排查时再按 id 去查 tutti-server 日志；本 Skill 不用 AWS、不拉 Server 日志。

**原 Task 只追加，不改写。** 这一轮的表现和现场都放在一条新评论里（格式见 [打回评论与附件](references/reopen-comment.md)），不用 `task edit` 改描述：描述是整段替换，原来挂的截图和日志会丢。标题、优先级、负责人保持不变；QA 明确要求换跟进人时才 `task edit --assignee-user-id`（只改负责人，不带描述）。

**先发评论，再改状态。** RD 看到 Task 回到待办时，打回原因已经在评论里。所有写操作都带 `--operation-id`，结果不确定时用同一个 ID 和相同输入重试；CLI 不会自动重试。

**登录过期就当场重新登录，不停下来问。** `whoami` 或 `task` 命令报 `No readable CLI session`、401、`run tutti-cli login` 时，后台运行 `tutti-cli login`：浏览器打开 Tutti 登录页，用户用自己的账号登录即可（最长等 5 分钟）。完成后 `whoami --json` 确认账号，再重跑刚才的命令。同时在对话里说一句「Tutti 登录已过期，已在浏览器打开登录页，完成登录即可」，继续等待，不结束本轮。只有等了 10 分钟仍没完成，或者 tutti-ops Token 失效（需要在管理端重新创建，见 `$tutti-bug-workflow:bug-setup`），才写进最终回复，并写清用户要做的一步。

**只说有证据的事实。** 对用户的每一句说明都要有命令输出、日志作证，照原样转述返回的字段和报错；没证实的写成「待确认：……」。QA 的说法和查到的结果对不上时，两边并列写出，不替任何一方下结论。

**不脱敏。** 现场日志原样采集、原样上传。

**无状态。** `operation_id`、`question_time`、`incident_at`、采集结果都记在本次会话上下文中。日志、截图等放在数据目录（默认 `~/.local/share/bug-workbench`，可用 `BUG_WORKBENCH_DATA` 改）下的 `bug-reports/<taskId>/reopen-<operation_id>/`（下称 `$REPORT`，用绝对路径）。对外唯一的事实来源是 Room 里的 Task。脚本路径相对本 Skill 目录（`skills/bug-reopen/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责；已有权限内的读取、召回、上传附件、发评论、把 Task 改回待办和交给 Room Agent 重新分析属于本任务授权，无需逐项再问。

写最终回复前逐项自查，任何一项没有结果且不是卡点，就回去做完：

| 自查项 | 必须有的结果 |
|---|---|
| Task | `task show` 读到了，`task.taskId`、`task.roomId` 是 QA 指的那条；记下标题和打回前的状态 |
| 评论 | `task comment` 回执 `status: posted`，记下 `commentId`；正文按 [打回评论与附件](references/reopen-comment.md#评论正文) 写清验收版本、复现步骤、实际、期望、和修复前相比 |
| 附件 | 评论带上了 QA 这一轮的截图／视频、`排查线索.txt` 和全部日志；缺的写进排查线索 |
| Web 日志 | `web-logs.log` 或 QA 导出包已挂到评论；或写明缺什么、怎么提供 |
| request id | `web_requests.py` 列出的故障附近失败请求（没有失败时取 `nearest_requests` 里相关的几条）和 Computer 日志里失败出站请求的 request id 已写进 `排查线索.txt` |
| Computer 日志 | 召回已完成，召回包已挂到评论；或写明受阻原因、待用户确认的设备 |
| 状态 | `task status --status todo` 回执的 `task.status` 为 `ROOM_TASK_STATUS_TODO`，`task show` 回读一致；打回前已是 `todo` 时不写，回复里说明 |
| 重新分析 | 已按 [交给 Room Agent 重新分析](references/rd-reanalysis.md) 用 `task run --reply-to <打回评论>` 发出，回执 `accepted` 且带 `invocationId`，记下 Agent、模型和 `invocationId`；重放后仍是 `pending` 的写明「Agent 尚未受理」；或写明为什么没发（QA 说不用分析、没有可用的 Agent／模型、被拒） |
| 原 Task | 标题、描述、描述里的附件、优先级都没被改动 |
| 会话上传 | 全部完成后已上传一次 |

## 1. 接收

1. **Task**：按顺序取 Room ID 和 Task ID，取到就停：
   1. **用户消息里的 Task 链接**（QA 可能只发了链接和截图，没有别的话）。链接形如 `https://tutti.sh/platform/room/<roomId>?surface=task-board&task=<taskId>`，两个都有。
   2. **用户消息里的 Task ID**：再问是哪个房间（可给房间名，用 `tutti-cli room list --all --json` 按名称找，本地房间优先）。
   3. **本会话前面提过的 Bug**：QA 说「之前提的 bug」「刚才那个」「上面那条」时，用本会话里 `task create`／`task show` 回执的 `task.roomId` 和 `task.taskId`。本会话提过多条时，按 QA 说的现象、功能和截图对照各条的标题和描述选；对不上或不止一条对得上时，把这几条的标题和链接列给 QA 选，不猜。
   4. 都没有：请 QA 发 Task 链接（CLI 列不出 Task，只有房间和标题时也要链接）。拿不到 Task 就停下，这是唯一必须先问的卡点。

   Task 来自本会话时，上一轮提 Bug 的现场线索可以直接复用：WebMCP 连接链接（页面可能已刷新，`download_web_logs` 匹配不到就当作没有）、当时定位到的 Computer（作为第 3.2 步的候选，以这一轮的 Web 日志为准）、`$REPORT` 里的 `description.txt` 和 `排查线索.txt`（写「和修复前相比」时对照）。
2. 从用户消息和截图整理这一轮验收（QA 只给了截图时，以截图里看到的为准，看不出来的写「待 QA 确认」）：验收的版本（PR、PPE 泳道、体验链接或生产）、复现步骤与频率、实际表现、期望、和修复前相比的变化、验收时间与时区、操作账号、截图／视频（实际查看）、WebMCP 连接链接、QA 附带的 Web 诊断包、用到的设备、要不要换跟进人、是否说了不用分析。用户原话与你的推断分开记。
3. 固定 `question_time`：触发本次打回的消息时间（含时区的 ISO 8601）；拿不到时用收到消息的时间并注明近似，取当前时间时精确到毫秒：`python3 -c 'from datetime import datetime; print(datetime.now().astimezone().isoformat(timespec="milliseconds"))'`。之后读 Web 日志用这同一个值，不再另取当前时间。
4. 固定 `incident_at`（这一轮看到问题的时间）：QA 说了什么时候验收、什么时候看到的（「上午验的」「刚才」），换算成含时区的 ISO 8601，只说到分钟就用该分钟的起点，并注明近似；Computer 与 Web 采集都覆盖故障前 10 分钟到后 5 分钟（截止不晚于 `question_time`），不能只覆盖到分钟起点；没说、或说的就是刚刚，等于 `question_time`。日志按它取，不按打回消息的时间取；`incident_at` 只是 QA 的大致说法时，在排查线索里注明。
5. 生成 `operation_id`：`python3 -c 'import uuid; print(uuid.uuid4())'`，用作本次打回评论的操作 ID（也是评论 ID）。创建 `$REPORT`。改状态另用一个新的 UUID，重试同一次写入时不变。

## 2. 读原 Task

```sh
tutti-cli task show --room-id <roomId> --task-id <taskId> --json
```

- 记下标题、描述、优先级、负责人和 `task.status`（如 `ROOM_TASK_STATUS_IN_REVIEW`）。描述就是 Bug 原来的表现，写评论的「期望」「和修复前相比」时对照它。
- 读不到（403、不存在）就停下，告诉用户原因，核对 `whoami` 的账号是否是该 Room 成员；未登录按上面的规则自动恢复。
- 打回前的状态是 `done`、`in_review`、`in_progress`、`blocked` 都照常打回，状态记进排查线索；已经是 `todo` 时仍发评论，第 5 步不再改状态。

## 3. 采集现场

和提 Bug 一样，现场以**这一轮看到问题**的时间为准（`incident_at`），设备也按这一轮验收用的来定。

### 3.1 Web 日志（主 agent，先做）

详见 [Web 日志](references/web-logs.md)。页面开在本机 Chrome 时，用 `chrome-devtools` MCP：

1. `list_pages` + `list_webmcp_tools` 按链接里的页面与 Account 匹配页面；QA 没给链接时，按房间找本机 Chrome 里开着的这个 Room 的页面，URL 带这条 `task=<taskId>` 的优先（规则见 [Web 日志](references/web-logs.md)）。记下页面 URL（「页面链接」）。
2. 用 `scripts/merge_web_logs.py --question-time <question_time> --incident-at <incident_at> --until-ms` 固定读取窗口，`execute_webmcp_tool` 调 `download_web_logs` 触发一次文件下载；确认本地文件完整后，用 `scripts/merge_web_logs.py --download <路径>` 校验并整理成 `$REPORT/web/web-logs.log`。工具只接收元数据，正文从本地文件按需读取（详见 [Web 日志](references/web-logs.md)）。
3. `execute_webmcp_tool` 调 `list_my_computers`（房间相关时加 `list_room_agents`），用于定位 Computer。

不刷新、不跳转页面。WebMCP 不可用、用户在另一台机器上或页面已刷新时，用 QA 导出的诊断包；两者都没有时记为 `pending`，第 7 步请用户导出。

### 3.2 Computer 日志（后台进程）

按 [Computer 定位](references/computer-target.md) 确定设备：优先 Web 日志里验收时间附近记录关联的 Computer，其次页面的 `list_my_computers`，再其次用户说的设备名。确定后立刻放到后台跑，不等它：

```sh
python3 scripts/collect_computer.py --computer-id ID --incident-at <incident_at> --question-time <question_time> --output-dir $REPORT/computer > $REPORT/computer.json &
```

有多个候选或没有线索时记为 `pending`，第 7 步请用户确认设备，确认后再跑。

### 3.3 请求与 request id（主 agent）

```sh
python3 scripts/web_requests.py --web-logs <web-logs.log 或诊断包 zip> --incident-at <incident_at>
```

`failed_requests`（看到问题前 10 分钟到后 5 分钟内失败的请求）全部写进排查线索的「日志核对」和「关联 ID」；`nearest_requests`（离那个时间最近的 10 条，不论成败）里和问题相关的也写上，没有失败时以它为准。`failed_outside_window` 是更早或更晚的失败，只在和问题明显相关时提一句。`without_request_id` 不为 0 说明是旧版 Web，那几条只记时间、method、路径、状态码。召回包里 `desktopd.log` 验收时间附近失败的出站请求（`desktop.outbound_network.api_request`）的 `request_id` 也写进排查线索（见 [Computer 日志里的 request id](references/computer-logs.md#日志里的-request-id)）。不去查服务端日志。

环境按页面链接和 QA 的说法判断：`tutti.sh` 是生产，PPE 写泳道名；拿不准写「待 QA 确认」。

## 4. 发打回评论

1. QA 的截图／视频复制到 `$REPORT`，日志留在各自目录。
2. 按 [打回评论与附件](references/reopen-comment.md) 把评论正文写到 `$REPORT/验收不通过.txt`、排查线索写到 `$REPORT/排查线索.txt`。
3. 等 Computer 召回结束（读 `$REPORT/computer.json`；召回在等用户确认设备时不等），正文和全部文件在**一次** `task comment` 里发出（命令和重试规则见 [发送与重试](references/reopen-comment.md#发送与重试)）。回执 `status: posted` 才算发出。

## 5. 改回待办

评论发出后：

```sh
tutti-cli task status --room-id <roomId> --task-id <taskId> --status todo --operation-id <新 UUID> --json
tutti-cli task show --room-id <roomId> --task-id <taskId> --json   # 回读状态，确认标题、描述没变
```

- 回执 `task.status` 为 `ROOM_TASK_STATUS_TODO` 才算成功。改状态不会打断、也不会启动 Agent 的执行，不会改负责人。
- 超时、断网等结果不确定时，先 `task show` 看状态：已经是 `todo` 就算成功；不是再用**同一个** `--operation-id` 重跑一次。同 ID 重放返回的是 Task 的当前状态，可能已经包含之后别人的改动，以 `task show` 为准。
- 报无权限（403）时不换别的方式改，记为卡点：评论已经发出，在最终回复里请 QA 在任务看板把这条 Task 拖回「待办」，并附上报错原文。
- QA 要求换跟进人时，用 `tutti-cli room members --room-id <roomId> --json` 找到对方的 userId，再 `tutti-cli task edit --room-id <roomId> --task-id <taskId> --assignee-user-id <userId> --operation-id <新 UUID> --json`（不带描述和附件）。

## 6. 交给 Room Agent 重新分析

Task 改回待办后（改状态被拒时照样做），按 [交给 Room Agent 重新分析](references/rd-reanalysis.md) 选该 Room 的 Agent 和模型（Codex 优先，用 `gpt-6.1-sol`，其次 `gpt-6-astra`；没有再用 Claude Code 的 Opus 5.5；推理强度都用 `high`），用模板把原 Bug、这一轮的表现和关键现场线索组织成 `$REPORT/rd-reanalysis.txt`，用 `tutti-cli task run --reply-to <打回评论的 commentId>` 发在打回评论的线程里。指令要求 Agent 先说清上一轮修复为什么没生效，再重新分析根因、出方案、画流程图，结果回复在同一个线程里。

**确保发送成功，然后就不管了**：回执是 `accepted` 且带 `invocationId` 才算成功；`pending` 用同一个操作 ID 重放、`rejected` 换下一个 Agent／模型，细则见引用文档。成功后直接继续第 7 步，不等 Agent 执行、不轮询它的回复、不转述分析结果。现场有缺项（召回在等设备、QA 还没给诊断包）时也照常发，缺什么写进指令的现场线索。

## 7. 收尾

1. 第 4 步发评论时还有现场没到（召回在等设备确认、QA 还没给 Web 诊断包）：到齐后按 [后到的现场](references/reopen-comment.md#后到的现场) 回复在打回评论的线程里，只带新文件，不重发已挂过的文件，不再改状态。第 6 步的重新分析发出时缺的正是这份现场的，这条回复直接用 `task run` 发给同一个 Agent 复核；没发分析（QA 说不用）或补充不影响分析时用 `task comment`。
2. 需要用户提供的东西一次列出，每项说明怎么获取：

   | 缺什么 | 怎么请用户提供 |
   |---|---|
   | Web 现场 | 在验收的 Tutti 页面打开「设置 → 诊断」，点「复制 WebMCP 连接链接」发过来并保持页面不刷新；或在同一浏览器「导出日志」（范围覆盖验收时间），把 zip 发过来 |
   | 故障设备 | 从列出的候选（名称、平台、版本）里选验收时用的那台；或直接提供设备名称／Computer ID |
   | 验收版本 | 「这一轮验收的是哪个版本？PR、PPE 泳道或体验链接都行」 |
   | 期望（没说清，或和原 Task 描述不一致时） | 把 QA 这次的说法和原 Task 描述里的期望并列，请 QA 确认 |
   | 状态没改成（无权限） | 「打回评论已发出，但你的账号没有权限改状态，请在任务看板把这条 Task 拖回待办」 |

   登录过期按上面的规则当场自动恢复，不列在这里；真正的工具缺失、权限不足才写进回复交给维护方。用户补充后在同一会话里继续，回复在同一个评论线程里；不重发分析指令（QA 明确要求再分析一次时再发）。
3. 按开头的自查表逐项确认；全部完成后按 [会话上传](references/session-upload.md) 上传本次会话一次。
4. 最终回复：Task 标题与链接（`https://tutti.sh/platform/room/<roomId>?surface=task-board&task=<taskId>`）、打回账号、打回前后的状态、评论里写的这一轮表现（一两句）、已挂上的截图和日志、重新分析交给了哪个 Agent 和模型（结果会回复在打回评论的线程里）、缺失项及需要用户提供的内容。不转述根因推测。
