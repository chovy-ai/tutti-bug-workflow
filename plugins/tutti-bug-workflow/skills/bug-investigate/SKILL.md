---
name: bug-investigate
description: QA 提 Bug（「记个 bug」「帮我提个 bug」「登记一下这个问题」，或 Multica 里分配给 Bug 守门员的 issue）：每次调用都走完全程——固定采集当时的现场日志（Web 页面日志、Computer 日志），记下相关请求的 request id 供 RD 之后查服务端日志，在 Multica 的 Bug 项目里登记 issue（标题是一句话简介，描述写清 Bug 表现），截图、排查线索文件和全部日志作为附件发在「现场材料」评论里，最后把 issue 分配给 Bug 分析 Agent 分析根因；自己不做根因分析，只有遇到自己无法解决的卡点才向用户提问。
---

# QA 提 Bug

你负责把一次上报变成 Multica 里一个**上下文完整**的 issue，交给分析 Agent 排查：登记 issue、采集当时的全部现场、把现场作为附件发到 issue、补全描述，再把 issue 分配给分析 Agent。**自己不分析根因，不读代码**；时间花在把现场带全、把 Bug 表现写清楚上。

**Multica issue 是这条 Bug 的唯一记录。** 分析结论、RD 的评审、修复结果都会落在同一个 issue 里，不另建 Tutti Task 或其他记录。

## Multica 命令

在 Multica 分配的任务里运行时（环境里有 `MULTICA_TOKEN`），直接用 `multica`，issue ID 就是任务提示里的「assigned issue ID」。在本机 Codex 里直接调用时，从数据目录（默认 `~/.local/share/bug-workbench`）`config.json` 的 `multica` 读 `profile` 和 `workspace_id`，每条命令前加 `multica --profile <profile> --workspace-id <workspace_id>`；`multica` 报未登录或找不到 workspace 时按 `$tutti-bug-workflow:bug-setup` 处理，不改用别的记录方式。下文的 `multica` 都按这个规则。

同一份配置里还有：`multica.project`（Bug 项目的名称，`multica project list --output json` 里按 `title` 找到它的 `id`）和 `multica.agents.analyze`（分析 Agent 的名称）。Agent 指令里写了交给谁时以指令为准。

**一旦调用就走完全程。** 「记个 bug」「帮我提个 bug」「登记一下」都执行第 1–5 步，没有「只登记」的模式。登记 issue 只是第 2 步，不能回复「已登记」就结束。

**连续执行，一次做完。**

- 每一步做完立刻开始下一步，中途不输出阶段总结，不问「要不要继续」「要不要采集日志」。
- 耗时操作在本轮内等它完成：Computer 远端召回最长约 25 分钟，期间并行做其他步骤，不把控制权交还给用户。
- 某一项卡住时记下原因，继续其他能做的；全部做完或全部卡住才写最终回复。

**尽量并行。** Web 日志先采（它给出失败请求的 request id 和 Computer 线索），随后 Computer 召回用后台进程跑，主 agent 同时整理上下文。

**不查服务端日志。** Web 和 Computer 日志里的请求都带网关的 request id（`x-zk-request-id`），提 Bug 时只把相关请求和它们的 request id 记进排查线索，RD 排查时再按 id 去查 tutti-server 日志；本 Skill 不用 AWS、不拉 Server 日志。

**描述只讲表现，线索放附件。** 标题是一句话 Bug 简介，描述只写问题、复现步骤、实际、期望等 Bug 表现，让没看过现场的人一看就懂；日志事实、各种 ID、版本这些排查线索写进附件 `排查线索.txt`。格式见 [issue 字段](references/issue-fields.md)。

**现场附件发在一条评论里。** `multica issue update` 不能加附件，所以 QA 的截图在建 issue 时用 `--attachment` 挂上（issue 已存在时和日志一起发），`排查线索.txt` 和全部日志等现场齐了在**一条**「现场材料」评论里用 `--attachment` 一次发出；后到的现场再发一条「现场补充」评论。限制和命名见 [现场材料与附件](references/registration-logs.md)。

**登录过期就当场处理，不停下来问。** Multica 由桌面端登录：`multica` 报 401 或未登录时，请用户打开 Multica 桌面端重新登录（在 Multica 任务里运行时不会出现）；tutti-ops Token 失效需要在管理端重新创建，见 `$tutti-bug-workflow:bug-setup`。等了 10 分钟仍没完成才写进最终回复，并写清用户要做的一步。

**只说有证据的事实。** 对用户的每一句说明（包括解释某一步为什么失败、为什么没发出去）都要有命令输出、日志或代码作证，照原样转述返回的字段和报错；没证实的写成「待确认：……」。用户的说法和查到的结果对不上时，两边并列写出，以待确认处理，不替任何一方下结论。

**不脱敏。** 现场日志原样采集、原样上传。

**无状态。** `operation_id`、`question_time`、issue ID、采集结果都记在本次会话上下文中。日志、截图等放在数据目录（默认 `~/.local/share/bug-workbench`，可用 `BUG_WORKBENCH_DATA` 改）下的 `bug-reports/<operation_id>/`（下称 `$REPORT`，用绝对路径）。对外唯一的事实来源是 Multica issue。脚本路径相对本 Skill 目录（`skills/bug-investigate/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责，已有权限内的读取、召回、上传附件，以及登记、编辑、分配 issue 属于本任务授权，无需逐项再问。

写最终回复前逐项自查，任何一项没有结果且不是卡点，就回去做完：

| 自查项 | 必须有的结果 |
|---|---|
| issue | 在 Bug 项目里新建（回执带 `id`、`identifier`），或沿用 Multica 分配给你的 issue／QA 指定的已有 issue；采集后已 `issue update` 写好标题、描述和优先级；`issue get` 回读一致 |
| 标题 | 一句话简介「功能：现象」，20–40 字，没有错误码、ID 和括号补充；说的是 QA 报的问题 |
| 优先级 | 按定义映射成 issue 优先级；拿不准时用 `none`，在描述「待 QA 确认」和回复里问 |
| Web 日志 | `web-logs.log` 或 QA 导出包已发到 issue；或写明缺什么、怎么提供 |
| request id | `web_requests.py` 列出的失败请求（没有失败时取问题时间附近的几条）和 Computer 日志里失败出站请求的 request id 已写进 `排查线索.txt` |
| Computer 日志 | 召回已完成，召回包已发到 issue；或写明受阻原因、待用户确认的设备 |
| 附件 | QA 的截图／视频在 issue 或「现场材料」评论上；「现场材料」评论带上了 `排查线索.txt` 和全部日志；`issue comment list` 回读附件一个不少 |
| 描述 | 只有问题、复现步骤、实际、期望、频率、发生时间、环境一行（和待 QA 确认），没有日志字段、ID、版本号 |
| 排查线索 | `排查线索.txt` 记下日志核对、关联 ID、环境与版本、分类；回复里提到的每条发现都在描述或这个文件里 |
| 交给分析 | `multica issue assign <issueId> --to <分析 Agent>` 成功，回执的 assignee 是分析 Agent；或写明为什么没交（Agent 不存在、分配失败的报错原文） |
| 会话上传 | 全部完成后已上传一次 |

## 1. 接收

1. 从用户消息或分配给你的 issue（`multica issue get <issueId> --output json`、`multica issue comment list <issueId> --output json`）整理：期望与实际表现、复现步骤与频率、发生时间与时区、操作账号、截图／视频（附件用 `multica attachment download <attachmentId> -o $REPORT` 下载后实际查看）、WebMCP 连接链接、QA 附带的 Web 诊断包、建议的跟进人、用到的设备。用户原话与你的推断分开记；QA 说的问题和期望原样保留，后面写标题、问题、期望都以它为准。
2. 固定 `question_time`：触发本次上报的消息时间（含时区的 ISO 8601），issue 里没写时用 issue 的 `created_at`；拿不到时用收到消息的时间并注明近似。
3. 生成 `operation_id`：`python3 -c 'import uuid; print(uuid.uuid4())'`，创建 `$REPORT`。
4. 判断分类（所属端、业务模块写进排查线索的「分类」）：
   - **所属端**：Mac／Windows／Web，按问题出现的位置判断。
   - **优先级**：用户（QA）给了就照填。没给时按定义判断：
     - **P0**：严重阻塞，核心流程走不下去、没有绕过办法，或数据丢失；
     - **P1**：明显的 Bug，功能结果不对、用户一眼能看出来；
     - **P2**：非核心功能的问题，或体验、展示上的小问题。

     对照描述能明确落到某一级才自己定；拿不准就用 `none`，在第 5 步问 QA（说明你倾向哪一级、为什么）。issue 优先级的映射见 [issue 字段](references/issue-fields.md#优先级)。
   - **业务模块**：用界面上的功能名称描述问题所在的功能（如「房间-群聊」「任务看板」），不确定时写「待 QA 确认」。

## 2. 登记 issue

1. **沿用还是新建**：Multica 把 issue 分配给你时就用它，不再新建；QA 给了已有 issue（编号如 `TES-123` 或链接）并说是同一个问题时，`multica issue get` 确认后沿用。否则新建。
2. **新建**：按 QA 的描述先起一个标题（规则见 [issue 字段](references/issue-fields.md#标题)），描述先写 QA 原话、发生时间和「现场采集中」，QA 的截图一起挂上：
   ```sh
   multica issue create --title "<标题>" --description "<QA 原话、发生时间；现场采集中>" \
     --project <Bug 项目 ID> --priority <urgent|high|medium|low|none> \
     --allow-external-file --attachment <$REPORT>/screenshot-1.png --output json
   ```
   记下回执的 `id` 和 `identifier`（如 `TES-123`）。超时等结果不确定时先 `multica issue search "<标题>"` 核对，确实没建成再重跑，不重复建单。

## 3. 采集现场

### 3.1 Web 日志（主 agent，先做）

详见 [Web 日志](references/web-logs.md)。用户给了 WebMCP 连接链接、页面开在本机 Chrome 时，用 `chrome-devtools` MCP：

1. `list_pages` + `list_webmcp_tools` 按链接里的页面与 Account 匹配页面，记下页面 URL（「页面链接」）。
2. `execute_webmcp_tool` 分页读 `get_web_logs`，每页存一个文件，用 `scripts/merge_web_logs.py` 合并成 `$REPORT/web/web-logs.log`。
3. `execute_webmcp_tool` 调 `list_my_computers`（房间相关时加 `list_room_agents`），用于定位 Computer。

不刷新、不跳转用户的页面。**链接对应的页面找不到（已刷新或关闭）时，不要直接记 `pending`**：只要本机 Chrome 里还有同一 Account 的 Tutti 页面，就自己新开一个标签页，从「设置 → 诊断」导出这个账号的历史日志（含已刷新的那次页面会话），见 [Web 日志 · 方式二](references/web-logs.md#方式二本机导出历史日志)。本机没有这个账号（用户在另一台机器上）时用 QA 导出的诊断包；都没有才记为 `pending`，第 5 步请用户导出。

### 3.2 Computer 日志（后台进程）

按 [Computer 定位](references/computer-target.md) 确定设备：优先 Web 日志里故障时间附近记录关联的 Computer，其次页面的 `list_my_computers`，再其次用户说的设备名。确定后立刻放到后台跑，不等它：

```sh
python3 scripts/collect_computer.py --computer-id ID --incident-at <question_time> --output-dir $REPORT/computer > $REPORT/computer.json &
```

有多个候选或没有线索时记为 `pending`，第 5 步请用户确认设备，确认后再跑。

### 3.3 请求与 request id（主 agent）

拿到 Web 日志后列出页面发往 tutti-server 的请求：

```sh
python3 scripts/web_requests.py --web-logs <web-logs.log 或诊断包 zip> --question-time <question_time>
```

`failed_requests`（失败的请求，带时间、method、路径、状态码、`request_ids`）全部写进排查线索的「日志核对」和「关联 ID」；没有失败时用 `nearest_requests`（问题时间附近的几条）里和问题相关的。`without_request_id` 不为 0 说明是旧版 Web，那几条只记时间、method、路径、状态码。不去查服务端日志。

环境按页面链接和 QA 的说法判断：`tutti.sh` 是生产，PPE 写泳道名；拿不准写「待 QA 确认」。

## 4. 补全描述与发出现场

1. 按 [现场材料与附件](references/registration-logs.md) 整理文件：QA 的截图／视频复制到 `$REPORT`，日志留在各自目录。
2. 按 [issue 字段](references/issue-fields.md) 把描述写到 `$REPORT/description.md`、排查线索写到 `$REPORT/排查线索.txt`，标题按规则改成一句话简介。召回包里 `desktopd.log` 故障时间附近失败的出站请求（`desktop.outbound_network.api_request`）的 `request_id` 也写进排查线索（见 [Computer 日志里的 request id](references/computer-logs.md#日志里的-request-id)）。
3. 等 Computer 召回结束（读 `$REPORT/computer.json`；召回在等用户确认设备时不等），先更新 issue，再把现场一次发出：
   ```sh
   multica issue update <issueId> --title "<标题>" --description "$(cat <$REPORT>/description.md)" --priority <优先级>
   multica issue comment add <issueId> --content-stdin --allow-external-file \
     --attachment <$REPORT>/排查线索.txt --attachment <$REPORT>/web/web-logs.log \
     --attachment <$REPORT>/computer/<召回包>.tar.gz --attachment <$REPORT>/screenshot-1.png < <$REPORT>/evidence.md
   multica issue get <issueId> --output json          # 回读标题、描述、优先级
   multica issue comment list <issueId> --output json # 回读「现场材料」评论和附件
   ```
   `evidence.md` 是这条评论的正文：第一行「现场材料」，然后每个附件一行说明（同 `排查线索.txt` 的「附件」一节），最后列出各类现场的采集状态（见 [采集结果状态](references/registration-logs.md#采集结果状态)）。建 issue 时已挂上的截图不再重复发。

上传失败时评论不会发出：按报错修正（文件名重复、空文件、文件过大）后重发；修不了的文件去掉，在排查线索里写一句缺什么和本机路径，继续。

4. **交给分析 Agent。** issue 回读无误后分配给分析 Agent，Multica 会让它立刻开始：
   ```sh
   multica issue assign <issueId> --to "<分析 Agent 名称>"
   ```
   回执的 assignee 是分析 Agent 才算交出。**交出就不管了**：不等它分析、不轮询、不转述分析结果。现场有缺项（召回在等设备、QA 还没给诊断包）时也照常交，缺什么已经写在「现场材料」评论里。分配失败（Agent 不存在、名称不对）时写进最终回复，带上报错原文。

## 5. 收尾

1. 第 4 步交出时还有现场没到（召回在等设备确认、QA 还没给 Web 诊断包）：到齐后补进 `排查线索.txt`，发一条「现场补充」评论，带上新到的文件和更新后的 `排查线索.txt`。
2. 需要用户提供的东西一次列出，每项说明怎么获取：

   | 缺什么 | 怎么请用户提供 |
   |---|---|
   | Web 现场 | 在出问题的 Tutti 页面打开「设置 → 诊断」，点「复制 WebMCP 连接链接」发过来并保持页面不刷新；或在同一浏览器「导出日志」（范围覆盖问题发生时间），把 zip 发过来 |
   | 故障设备 | 从列出的候选（名称、平台、版本）里选当时用的那台；或直接提供设备名称／Computer ID |
   | 优先级（拿不准时） | 「这条按 P1（明显 Bug，对应 high）合适吗？」，附一句判断理由；确认后 `multica issue update --priority` 修改 |
   | 期望（没说清，或现场事实与 QA 的说法不一致时） | 把 QA 的说法和查到的事实并列，请 QA 确认期望，例如「你说是同一份文件，记录里三条内容各不相同：期望只显示最新一份，还是保留历史但标出版本？」 |

   在 Multica 任务里运行时，这些问题写成 issue 评论；QA 在评论里补充后同一个 issue 继续：更新 `description.md`／`排查线索.txt`，`issue update` 一次，新文件发「现场补充」评论；不再建第二个 issue。
3. 按开头的自查表逐项确认；全部完成后按 [会话上传](references/session-upload.md) 上传本次会话一次。
4. 最终回复：issue 编号与标题、优先级、环境、已发出的截图和日志、交给了哪个分析 Agent（结果会回复在 issue 评论里）、缺失项及需要用户提供的内容。
