---
name: bug-investigate
description: QA 提 Bug（「记个 bug」「帮我提个 bug」「登记一下这个问题」等都算；QA 发来已有 Task 的链接、说这个问题还在或要打回时不用本 Skill，用 bug-reopen；本会话里提过的 Bug 已经修过、QA 说它还有问题时也用 bug-reopen）：每次调用都走完全程——固定采集当时的现场日志（Web 页面日志、Computer 日志），记下相关请求的 request id 供 RD 之后查服务端日志，用全局安装的 `tutti-cli`（账号登录版）以 QA 的账号在指定 Room 建 Task，再用 `task edit` 把标题改成一句话简介、描述写清 Bug 表现，截图、排查线索文件和全部日志作为附件挂上，最后用 `task run` 把组织好的分析指令交给该 Room 的 Agent（Codex 优先，用 gpt-6.1-sol 或 gpt-6-astra；其次 Claude Code 用 Opus 5.5；推理强度都是 high）分析根因、出方案、画修复前后流程图并回复在 Task 里；自己不做根因分析，只有遇到自己无法解决的卡点才向用户提问。
---

# QA 提 Bug

你负责把一次上报变成指定 Room 里一个**上下文完整**的 Task，交给 RD 排查：建 Task、采集当时的全部现场、把现场作为附件挂到 Task、补全描述，再把根因分析交给 Room 里的 Agent。**自己不分析根因，不读代码**；时间花在把现场带全、把分析指令写清楚上。

**用全局安装的 `tutti-cli` 建 Task。** 它是 npm 包 `@tutti-os/tutti-cli`（Node.js 24+），以本机 `tutti-cli login` 登录的 Tutti 账号直接调用 Tutti 服务，不依赖 Computer 或 Room Agent，在 QA 本机的 Codex／Claude Code 里就能跑；创建者就是这个账号，权限按它在目标 Room 的成员身份判断。开始前运行 `tutti-cli --help` 和 `tutti-cli whoami --json`：

- `--help` 里没有 `login`：没装，或 PATH 里先找到的是 Computer 自带的 Agent 版 `tutti-cli`。改用 `"$(npm prefix -g)/bin/tutti-cli"`；仍没有就按 `$tutti-bug-workflow:bug-setup` 安装，不改用别的建单方式。
- 确认可用的那个路径记为 `TUTTI_CLI`（如 `export TUTTI_CLI="$(npm prefix -g)/bin/tutti-cli"`），本 Skill 里所有 `tutti-cli` 命令都用它，`find_room.py` 也读这个环境变量（或传 `--cli "$TUTTI_CLI"`），不再依赖 PATH 里排在前面的那个。
- `whoami` 报未登录或会话失效：按下面「登录过期」自动恢复。

它有 `login`／`whoami`／`logout`、`room list`、`agent list`／`models` 和 `task create`／`edit`／`show`／`comment`／`run`：**没有查重列表、指派、改优先级**，每条 `task` 和 `agent` 命令都要显式带 `--room-id`。排查线索写成一个文本文件，和日志一起作为附件挂在描述上（见下）；跟进人请 QA 在任务看板指派。

**先查房间，再定 Room。** 用 `scripts/find_room.py --query "<QA 给的线索>"` 在当前账号的房间列表（`tutti-cli room list --json`）里找要建单的 Room，线索可以是：

- **Room ID**，或带 `/room/<roomId>` 的 Room／Task 链接：必须在列表里，否则当作没找到；
- **房间名或用户名**（房间一般以主人命名，如「Tutti-Chovy 1012」「TIBO 本地房间」）：不区分大小写，先在**本地房间**里找，本地没有匹配才找云端房间；名称完全相同优先于部分包含。

结果 `matched` 就用 `room.id` 作为 `--room-id`，回复里写上房间名；`ambiguous` 把 `candidates`（名称、本地／云端）列给 QA 选；`not_found` 把 `local_rooms` 列给 QA 选。QA 什么都没给时，用 WebMCP 页面 URL（3.1 第 1 步）里的 Room ID 当线索；仍没有就先采集，在第 5 步连同本地房间列表一起问。只能建到当前账号能看到的 Room。

**一旦调用就走完全程。** 「记个 bug」「帮我提个 bug」「登记一下」都执行第 1–5 步，没有「只登记」的模式。建 Task 只是第 2 步，不能回复「已登记」就结束。

**连续执行，一次做完。**

- 每一步做完立刻开始下一步，中途不输出阶段总结，不问「要不要继续」「要不要采集日志」。
- 耗时操作在本轮内等它完成：Computer 远端召回最长约 25 分钟，期间并行做其他步骤，不把控制权交还给用户。
- 某一项卡住时记下原因，继续其他能做的；全部做完或全部卡住才写最终回复。

**尽量并行。** Web 日志先采（它给出失败请求的 request id 和 Computer 线索），随后 Computer 召回用后台进程跑，主 agent 同时整理上下文。

**不查服务端日志。** Web 和 Computer 日志里的请求都带网关的 request id（`x-zk-request-id`），提 Bug 时只把相关请求和它们的 request id 记进排查线索，RD 排查时再按 id 去查 tutti-server 日志；本 Skill 不用 AWS、不拉 Server 日志。

**先建 Task，再补全。** 第 2 步按 QA 的描述先建好 Task，本会话自建且保留全部原附件时，采集完用 `tutti-cli task edit` 改标题、写全描述并挂上附件。**优先级只能在创建时设置**，CLI 不能修改，建单时就要定好。所有写操作都带 `--operation-id`，结果不确定时用同一个 ID 和相同输入重试；CLI 不会自动重试。带 `--file` 的写入例外：每次上传都会生成新的附件，结果不确定时先 `task show` 核对，确实没生效再换一个新的操作 ID 重跑，不用同一个 ID 配不同的附件。

**描述只讲表现，线索放附件。** 标题是一句话 Bug 简介，描述只写问题、复现步骤、实际、期望等 Bug 表现，让没看过现场的人一看就懂；日志事实、各种 ID、版本这些排查线索写进附件 `排查线索.txt`。格式见 [Task 字段](references/report-fields.md)。

**复用已有 Task 的现场始终追加评论。** 第 4、5 步及所有引用文档里的描述编辑规则只用于本会话自建且保留全部原附件的 Task；复用 Task 用 `task comment --file`，后到现场同样追加，分析与复核指令注明评论 `commentId`。

**现场附件直接挂在 Task 上。** `task edit` 的 `--file <路径>` 可重复，把本机文件上传为 Task 的私有附件，只有 Room 成员能下载，本地房间和云端房间都能用。附件嵌在描述里：带 `--file` 时必须同时给出新描述（`--description-file`），`task edit` 整段替换描述，**没有再次带上的文件会从 Task 上消失**。所以每次带附件的 `task edit` 都要带上全部文件（截图、`排查线索.txt`、全部日志），尽量等现场齐了只提交一次。限制和命名见 [现场材料与附件](references/registration-logs.md)。

**登录过期就当场重新登录，不停下来问。** 认证失效不是卡点：

| 入口 | 怎么自动恢复 |
|---|---|
| Tutti 账号（建 Task） | `whoami` 或 `task` 命令报 `No readable CLI session`、401、`run tutti-cli login` 时，后台运行 `tutti-cli login`：浏览器打开 Tutti 登录页，用户用自己的账号登录即可（最长等 5 分钟）。完成后 `whoami --json` 确认账号，再重跑刚才的命令；写操作仍按上面的规则判断能不能用同一个操作 ID |

自动登录的同时在对话里说一句「Tutti 登录已过期，已在浏览器打开登录页，完成登录即可」，然后继续等待，不结束本轮。只有等了 10 分钟仍没完成，或者 tutti-ops Token 失效（需要在管理端重新创建，见 `$tutti-bug-workflow:bug-setup`），才写进最终回复，并写清用户要做的一步。

**只说有证据的事实。** 对用户的每一句说明（包括解释某一步为什么失败、为什么没发出去）都要有命令输出、日志或代码作证，照原样转述返回的字段和报错；没证实的写成「待确认：……」，不把接口返回的状态当成真实情况来推断原因（例如目录返回 `requestable` 不等于「当时没共享」）。用户的说法和查到的结果对不上时，两边并列写出，以待确认处理，不替任何一方下结论。

**不脱敏。** 现场日志原样采集、原样上传。

**无状态。** `operation_id`、`question_time`、`incident_at`、采集结果都记在本次会话上下文中。日志、截图等放在数据目录（默认 `~/.local/share/bug-workbench`，可用 `BUG_WORKBENCH_DATA` 改）下的 `bug-reports/<operation_id>/`（下称 `$REPORT`，用绝对路径）。对外唯一的事实来源是 Room 里的 Task。脚本路径相对本 Skill 目录（`skills/bug-investigate/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责，已有权限内的读取、召回、上传附件，以及建 Task、编辑属于本任务授权，无需逐项再问。

写最终回复前逐项自查，任何一项没有结果且不是卡点，就回去做完：

| 自查项 | 必须有的结果 |
|---|---|
| Room | `find_room.py` 结果为 `matched`，或 QA 从候选里选定；回复里写明房间名 |
| Task | `task create --room-id` 成功，回执 `task.taskId` 等于 `operation_id`、`task.roomId` 是目标 Room（或复用了 QA 指定的已有 Task）；采集后自建 Task 已 `task edit` 写好描述并回读；复用 Task 已追加评论且回执 `status: posted`、带 `commentId`，`task show` 确认原标题、描述和附件未变 |
| 跟进人 | CLI 不能指派：回复里请 QA 在任务看板指派，QA 提到的人写进 `排查线索.txt` 的「建议跟进人」 |
| 标题 | 一句话简介「功能：现象」，20–40 字，没有错误码、ID 和括号补充；说的是 QA 报的问题 |
| 优先级 | 建单时按定义映射成 Task 优先级；拿不准时用 `none`，在描述「待 QA 确认」和回复里问，QA 确认后在任务看板修改 |
| Web 日志 | `web-logs.log` 或 QA 导出包已挂到 Task；或写明缺什么、怎么提供 |
| request id | `web_requests.py` 列出的故障附近失败请求（没有失败时取 `nearest_requests` 里相关的几条）和 Computer 日志里失败出站请求的 request id 已写进 `排查线索.txt` |
| Computer 日志 | 召回已完成，召回包已挂到 Task；或写明受阻原因、待用户确认的设备 |
| 附件 | 自建 Task 最后一次 `task edit` 带上全部文件并回读 `uploadedFile`；复用 Task 的追加评论带上本次截图／视频、`排查线索.txt` 和全部日志，回执确认发布，原描述附件不变 |
| 描述 | 只有问题、复现步骤、实际、期望、频率、发生时间、环境一行（和待 QA 确认），没有日志字段、ID、版本号 |
| 排查线索 | `排查线索.txt` 记下日志核对、关联 ID、环境与版本、分类；回复里提到的每条发现都在描述或这个文件里 |
| 根因分析 | 已按 [交给 Room Agent 分析](references/rd-analysis.md) 用 `task run` 发出分析指令，回执 `accepted` 且带 `invocationId`，记下 Agent、模型和 `invocationId`；重放后仍是 `pending` 的写明「Agent 尚未受理」；或写明为什么没发（没有可用的 Agent／模型、被拒） |
| 会话上传 | 全部完成后已上传一次 |

## 1. 接收

1. 从用户消息整理：期望与实际表现、复现步骤与频率、发生时间与时区、操作账号、截图／视频（实际查看）、WebMCP 连接链接、QA 附带的 Web 诊断包、建议的跟进人、用到的设备。用户原话与你的推断分开记；QA 说的问题和期望原样保留，后面写标题、问题、期望都以它为准。
2. 固定 `question_time`：触发本次上报的消息时间（含时区的 ISO 8601）；拿不到时用收到消息的时间并注明近似，取当前时间时精确到毫秒：`python3 -c 'from datetime import datetime; print(datetime.now().astimezone().isoformat(timespec="milliseconds"))'`。之后读 Web 日志用这同一个值，不再另取当前时间。
3. 固定 `incident_at`（故障发生时间）：QA 说了什么时候遇到的（「10 点左右」「刚才」「昨晚」），换算成含时区的 ISO 8601，只说到分钟就用该分钟的起点，并注明近似；Computer 与 Web 采集都覆盖故障前 10 分钟到后 5 分钟（截止不晚于 `question_time`），不能只覆盖到分钟起点；没说、或说的就是刚刚，等于 `question_time`。日志按它取，不按上报时间取：QA 10:00 遇到、10:30 才报时，Web 日志、Computer 召回和请求都要覆盖 10:00 前后。`incident_at` 只是 QA 的大致说法时，在排查线索里注明。
4. 生成 `operation_id`：`python3 -c 'import uuid; print(uuid.uuid4())'`。它同时是 Task ID 和建 Task 的幂等键，本次上报全程只用这一个；建 Task 结果不确定时用同一个 ID 和相同参数重试，不会重复建单。创建 `$REPORT`。之后每次 `task edit` 各自生成一个新的操作 ID，重试同一次写入时不变。
5. 判断分类（所属端、业务模块写进排查线索的「分类」，Task 没有对应字段）：
   - **所属端**：Mac／Windows／Web，按问题出现的位置判断。
   - **优先级**：用户（QA）给了就照填。没给时按定义判断：
     - **P0**：严重阻塞，核心流程走不下去、没有绕过办法，或数据丢失；
     - **P1**：明显的 Bug，功能结果不对、用户一眼能看出来；
     - **P2**：非核心功能的问题，或体验、展示上的小问题。

     对照描述能明确落到某一级才自己定；拿不准就用 `none` 建单，在第 5 步问 QA（说明你倾向哪一级、为什么），QA 确认后在任务看板修改（CLI 改不了优先级）。Task 优先级的映射见 [Task 字段](references/report-fields.md#优先级)。
   - **业务模块**：用界面上的功能名称描述问题所在的功能（如「房间-群聊」「任务看板」），不确定时写「待 QA 确认」。

## 2. 建 Task

1. **确定 Room 和是否复用**：按开头「先查房间」的规则用 `find_room.py` 取 `roomId`。QA 给的是已有 Task 链接（带 `task=<taskId>`），说这个问题修过了还在、要打回或验收没过时，不在这里复用：交给 `$tutti-bug-workflow:bug-reopen`，它把这一轮现场评论到原 Task 并改回待办，不重写描述（重写会丢掉第一轮的附件）。QA 给了已有 Task 链接、说是还没修过的同一个问题（只是补充现场）时，`tutti-cli task show --room-id <roomId> --task-id <taskId> --json` 确认后复用它，**不改它的描述**：它的描述和附件是别人（或别的会话）挂的，本机没有原文件，`task edit` 整段替换会把它们丢掉。这一次的现场改用 `task comment --file` 追加成一条评论（正文写这次看到的表现，格式同描述，附件同第 4 步），标题、描述保持不变；第 4 步以及第 5 步所有后到现场的 `task edit` 都换成追加评论，记录每次回执的 `commentId`，复核指令指向对应评论的附件。只有本会话自己建的 Task（本机有它的全部文件）才用 `task edit` 整段更新。CLI 不能列出 Task，不做自动查重。还拿不到 `roomId`（没线索、多个候选或没找到）时跳过本步，先做第 3 步，Web 日志给出页面 URL 后再查一次。
2. **建单**：按 QA 的描述先起一个标题（规则见 [Task 字段](references/report-fields.md#标题)），描述先写 QA 原话、发生时间和「现场采集中」：
   ```sh
   tutti-cli task create --room-id <roomId> --operation-id <operation_id> --title "<标题>" \
     --description "<QA 原话、发生时间；现场采集中>" --priority <urgent|high|medium|low|none> --json
   ```
   回执 `task.taskId` 应等于 `operation_id`、`task.roomId` 等于 `roomId`。超时等结果不确定时用同一个 `--operation-id` 和相同参数重试；参数校验错误先修正再重试。报无权限时，核对 `whoami` 的账号是否是该 Room 成员，记为卡点问 QA。

## 3. 采集现场

### 3.1 Web 日志（主 agent，先做）

详见 [Web 日志](references/web-logs.md)。页面开在本机 Chrome 时，用 `chrome-devtools` MCP：

1. `list_pages` + `list_webmcp_tools` 按链接里的页面与 Account 匹配页面；QA 没给链接时，按房间找本机 Chrome 里开着的这个 Room 的页面（规则见 [Web 日志](references/web-logs.md)）。记下页面 URL（「页面链接」）。
2. 用 `scripts/merge_web_logs.py --question-time <question_time> --incident-at <incident_at> --until-ms` 固定读取窗口，`execute_webmcp_tool` 调 `download_web_logs` 触发一次文件下载；确认本地文件完整后，用 `scripts/merge_web_logs.py --download <路径>` 校验并整理成 `$REPORT/web/web-logs.log`。工具只接收元数据，正文从本地文件按需读取（详见 [Web 日志](references/web-logs.md)）。
3. `execute_webmcp_tool` 调 `list_my_computers`（房间相关时加 `list_room_agents`），用于定位 Computer。

不刷新、不跳转页面。WebMCP 不可用、用户在另一台机器上或页面已刷新时，用 QA 导出的诊断包；两者都没有时记为 `pending`，第 5 步请用户导出。

### 3.2 Computer 日志（后台进程）

按 [Computer 定位](references/computer-target.md) 确定设备：优先 Web 日志里故障时间附近记录关联的 Computer，其次页面的 `list_my_computers`，再其次用户说的设备名。确定后立刻放到后台跑，不等它：

```sh
python3 scripts/collect_computer.py --computer-id ID --incident-at <incident_at> --question-time <question_time> --output-dir $REPORT/computer > $REPORT/computer.json &
```

有多个候选或没有线索时记为 `pending`，第 5 步请用户确认设备，确认后再跑。

### 3.3 请求与 request id（主 agent）

拿到 Web 日志后列出页面发往 tutti-server 的请求：

```sh
python3 scripts/web_requests.py --web-logs <web-logs.log 或诊断包 zip> --incident-at <incident_at>
```

`failed_requests`（故障前 10 分钟到后 5 分钟内失败的请求，带时间、method、路径、状态码、`request_ids`）全部写进排查线索的「日志核对」和「关联 ID」；`nearest_requests`（故障时间最近的 10 条，不论成败）里和问题相关的也写上，没有失败时以它为准。`failed_outside_window` 是诊断包里更早或更晚的失败，只在和问题明显相关时提一句，不混进故障附近的请求。`without_request_id` 不为 0 说明是旧版 Web，那几条只记时间、method、路径、状态码。不去查服务端日志。

环境按页面链接和 QA 的说法判断：`tutti.sh` 是生产，PPE 写泳道名；拿不准写「待 QA 确认」。

## 4. 补全描述与排查线索

1. 按 [现场材料与附件](references/registration-logs.md) 整理文件：QA 的截图／视频复制到 `$REPORT`，日志留在各自目录。
2. 按 [Task 字段](references/report-fields.md) 把描述写到 `$REPORT/description.txt`、排查线索写到 `$REPORT/排查线索.txt`，标题按规则改成一句话简介。
3. 等 Computer 召回结束（读 `$REPORT/computer.json`；召回在等用户确认设备时不等）。复用已有 Task 时，用 `tutti-cli task comment --room-id <roomId> --task-id <taskId> --content-file <$REPORT>/description.txt --file <本次文件> --operation-id <新 UUID> --json`（`--file` 可重复，重试规则见 [现场材料与附件](references/registration-logs.md)） 追加，记下 `status: posted` 和 `commentId`，不执行下面的 `task edit`；以下编辑命令只用于本会话自建且保留全部原附件的 Task，描述、线索和全部文件在**一次** `task edit` 里提交：
   ```sh
   tutti-cli task edit --room-id <roomId> --task-id <taskId> --title "<标题>" \
     --description-file <$REPORT>/description.txt \
     --file <$REPORT>/screenshot-1.png --file <$REPORT>/排查线索.txt \
     --file <$REPORT>/web/web-logs.log \
     --file <$REPORT>/computer/<召回包>.tar.gz --operation-id <新 UUID> --json
   tutti-cli task show --room-id <roomId> --task-id <taskId> --json   # 回读标题、描述和附件
   ```
   召回包里 `desktopd.log` 故障时间附近失败的出站请求（`desktop.outbound_network.api_request`）的 `request_id` 也写进排查线索（见 [Computer 日志里的 request id](references/computer-logs.md#日志里的-request-id)）。

上传失败时 Task 不会被修改：按报错修正（文件名重复、空文件、超过 500 MiB、HTML／SVG 等）后重跑；修不了的文件去掉，在排查线索里写一句缺什么，继续。

4. **交给 Room Agent 分析根因。** Task 回读无误后，按 [交给 Room Agent 分析](references/rd-analysis.md) 选该 Room 的 Agent 和模型（Codex 优先，用 `gpt-6.1-sol`，其次 `gpt-6-astra`；没有再用 Claude Code 的 Opus 5.5；推理强度都用 `high`），用模板把 Bug 表现和关键现场线索组织成 `$REPORT/rd-analysis.txt`，`tutti-cli task run` 发出。指令要求 Agent 拉代码分析根因、先弄清模块整体设计再出方案、画修复前后的工作流程图，结果回复在 Task 的评论线程里。**确保发送成功，然后就不管了**：回执是 `accepted` 且带 `invocationId` 才算成功；`pending` 用同一个操作 ID 重放、`rejected` 换下一个 Agent／模型，细则见引用文档。成功后直接继续第 5 步，不等 Agent 执行、不轮询它的回复、不转述分析结果。现场有缺项（召回在等设备、QA 还没给诊断包）时也照常发，缺什么写进指令的现场线索。

## 5. 收尾

1. 第 4 步提交时还有现场没到（召回在等设备确认、QA 还没给 Web 诊断包）：到齐后补进 `排查线索.txt`，按 Task 来源提交：本会话自建且本机保留全部附件的 Task，再 `task edit` 一次，**带上全部文件**（之前挂过的也要再带，否则会从 Task 上消失）；复用已有 Task 时，继续用 `task comment --file` 追加现场，记下回执 `commentId`，不改标题、描述及原附件。如果第 4 步的分析指令发出时缺的正是这份现场（指令里写了缺什么），补齐后用 `task run --reply-to <分析指令的 commentId>` 交给同一个 Agent 和模型复核一次（见 [补齐现场后复核](references/rd-analysis.md#补齐现场后复核)）；不影响分析的小补充不发。
2. 需要用户提供的东西一次列出，每项说明怎么获取：

   | 缺什么 | 怎么请用户提供 |
   |---|---|
   | Web 现场 | 在出问题的 Tutti 页面打开「设置 → 诊断」，点「复制 WebMCP 连接链接」发过来并保持页面不刷新；或在同一浏览器「导出日志」（范围覆盖问题发生时间），把 zip 发过来 |
   | 故障设备 | 从列出的候选（名称、平台、版本）里选当时用的那台；或直接提供设备名称／Computer ID |
   | Room（拿不到 `roomId` 时） | 「这条 Bug 建在哪个房间？回复房间名、房主名字或 Room ID 都行」，附上 `find_room.py` 给出的候选或本地房间列表（名称 + 本地／云端） |
   | 跟进人 | CLI 不能指派：「建好了，请在任务看板把这条 Bug 指派给跟进人」 |
   | 优先级（拿不准时） | 「这条按 P1（明显 Bug，对应 high）合适吗？」，附一句判断理由；确认后请 QA 在任务看板修改 |
   | 期望（没说清，或现场事实与 QA 的说法不一致时） | 把 QA 的说法和查到的事实并列，请 QA 确认期望，例如「你说是同一份文件，记录里三条内容各不相同：期望只显示最新一份，还是保留历史但标出版本？」 |

   登录过期按上面的规则当场自动恢复，不列在这里；真正的工具缺失、权限不足才写进回复交给维护方。用户补充后在同一会话里继续：更新 `description.txt`／`排查线索.txt`；本会话自建且保留全部附件时带上全部文件 `task edit` 一次，复用已有 Task 时用 `task comment --file` 追加并记下 `commentId`；不再建第二个 Task。补充前先 `task show` 看状态：已经是 `in_review` 或 `done`（修过了），或 QA 说修过了还有问题、要打回、加评论打回时，不再改描述，交给 `$tutti-bug-workflow:bug-reopen`，Task 用本会话里的这一条，不用 QA 再发链接。
3. 按开头的自查表逐项确认；全部完成后按 [会话上传](references/session-upload.md) 上传本次会话一次。
4. 最终回复：房间名、Task 标题与链接（`https://tutti.sh/platform/room/<roomId>?surface=task-board&task=<taskId>`）、建单账号、优先级、请 QA 指派跟进人、环境、已挂上的截图和日志、根因分析交给了哪个 Agent 和模型（结果会回复在 Task 评论里）、缺失项及需要用户提供的内容。
