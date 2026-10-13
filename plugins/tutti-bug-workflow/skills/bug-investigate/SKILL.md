---
name: bug-investigate
description: QA 提 Bug（「记个 bug」「帮我提个 bug」「登记一下这个问题」等都算）：每次调用都走完全程——固定采集当时的现场日志（Web 页面日志、tutti-server 日志、Computer 日志），把日志发布到当前 Room，再用 `tutti-cli task create` 在当前 Room 创建一个带完整上下文的 Task；不做根因分析，只有遇到自己无法解决的卡点才向用户提问。
---

# QA 提 Bug

你负责把一次上报变成当前 Room 里一个**上下文完整**的 Task，交给 RD 排查：采集当时的全部现场、发布日志、建 Task。**不分析根因，不读代码**；时间花在把现场带全上。

**只能在 Tutti Room 的 Agent 会话里运行。** Task 由 `tutti-cli task create` 在**当前 Room** 创建，这个命令只在 Tutti 托管的 Agent 执行中可用（Native 或 VM Agent），创建者是这台 Computer 当前登录的 Account。开始前运行 `tutti-cli task create --help`：命令不存在，或执行时报 `task creation is available only inside a managed Agent execution`，说明不在 Tutti Agent 会话里，直接告诉用户「请在要登记 Bug 的 Room 里，让 Agent 执行这条上报」，不要改用别的建单方式。用 **Native Agent**（跑在 QA 本机的 Computer 上）：采集要用本机的 Chrome（WebMCP）、AWS CLI、tutti-ops 和本插件，VM Agent 里没有这些；只能用 VM Agent 时照常建 Task，取不到的现场按卡点记录。

**一旦调用就走完全程。** 「记个 bug」「帮我提个 bug」「登记一下」都执行第 1–5 步，没有「只登记」的模式。

**连续执行，一次做完。**

- 每一步做完立刻开始下一步，中途不输出阶段总结，不问「要不要继续」「要不要采集日志」。
- 耗时操作在本轮内等它完成：Computer 远端召回最长约 25 分钟，期间并行做其他步骤，不把控制权交还给用户。
- 某一项卡住时记下原因，继续其他能做的；全部做完或全部卡住才写最终回复。

**尽量并行。** Web 日志先采（它给出要对到服务端的请求和 Computer 线索），随后三件事同时进行：Computer 召回用后台进程跑，Server 日志交给 subagent 查，主 agent 整理上下文。宿主不支持 subagent 时，Server 也用后台进程跑。

**Task 建好后不能再用 CLI 修改。** `tutti-cli` 只能创建 Task，不能改标题、描述或优先级，也不能指派。所以 Task 放在最后一步建：现场采集完、附件发布完、上下文写全之后一次建好。之后的补充由 QA 在 Tutti 里直接编辑 Task。

**登录过期就当场重新登录，不停下来问。** 认证失效不是卡点：

| 入口 | 怎么自动恢复 |
|---|---|
| AWS（Server 日志） | `collect_server.py` 遇到 SSO 过期会自己运行 `aws sso login`，浏览器在本机弹出，用户在浏览器里点「允许」即可，脚本随后重试。结果里 `login.ok` 为 true 就照常继续 |

自动登录的同时在对话里说一句「AWS 登录已过期，已在浏览器打开授权页，点一下允许即可」，然后继续等待，不结束本轮。只有等了 10 分钟仍没完成、没有配置 SSO，或者 tutti-ops Token 失效（需要在管理端重新创建，见 `$tutti-bug-workflow:bug-setup`），才写进最终回复，并写清用户要做的一步。

**不脱敏。** 现场日志原样采集、原样发布。

**无状态。** `operation_id`、`question_time`、采集结果都记在本次会话上下文中。日志、截图等放在当前 Room 目录下的 `bug-reports/<operation_id>/`（下称 `$REPORT`，用绝对路径；`tutti-cli artifact publish` 只接受 Room 目录内的文件）。对外唯一的事实来源是 Room 里的 Task。脚本路径相对本 Skill 目录（`skills/bug-investigate/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责，已有权限内的读取、召回、发布与建 Task 属于本任务授权，无需逐项再问。

写最终回复前逐项自查，任何一项没有结果且不是卡点，就回去做完：

| 自查项 | 必须有的结果 |
|---|---|
| Task | `tutti-cli task create` 成功，回执里的 `task.taskId` 等于 `operation_id`；`tutti-cli task show` 回读标题、描述、优先级一致；或已按第 5 步把问题一次问完、等 QA 回复后再建 |
| 标题 | 一行写清「类别：现象（触发条件／关键对照）」；没看过现场的人单看这一行也能明白哪里不对，说的是 QA 报的问题 |
| 优先级 | 按定义映射成 Task 优先级；拿不准时用 `none`，并在描述「待 QA 确认」和回复里问 |
| Web 日志 | `web-logs.log` 或 QA 导出包已发布；或写明缺什么、怎么提供 |
| Server 日志 | `captured`／`empty`／`blocked`（附原因）；登录过期已自动重新登录并重试过 |
| Computer 日志 | 召回已完成并发布；或写明受阻原因、待用户确认的设备 |
| 附件 | QA 的截图／视频与全部日志已用 `tutti-cli artifact publish` 发布，描述的「附件」段列出了它们 |
| 描述 | 以「概要」「现场核对」开头，回复里提到的每条发现都在这两段里；环境与版本、页面链接、关联 ID 齐全 |
| 会话上传 | 全部完成后已上传一次 |

## 1. 接收

1. 从用户消息整理：期望与实际表现、复现步骤与频率、发生时间与时区、操作账号、截图／视频（实际查看）、WebMCP 连接链接、QA 附带的 Web 诊断包、建议的跟进人、用到的设备。用户原话与你的推断分开记；QA 说的问题和期望原样保留，后面写标题、概要、期望都以它为准。
2. 固定 `question_time`：触发本次上报的消息时间（含时区的 ISO 8601）；拿不到时用收到消息的时间并注明近似。
3. 生成 `operation_id`：`python3 -c 'import uuid; print(uuid.uuid4())'`。它同时是 Task ID 和建 Task 的幂等键，本次上报全程只用这一个；建 Task 结果不确定时用同一个 ID 和相同参数重试，不会重复建单。创建 `$REPORT`。
4. 判断分类，写进描述的开头（Task 没有对应字段）：
   - **所属端**：Mac／Windows／Web，按问题出现的位置判断。
   - **优先级**：用户（QA）给了就照填。没给时按定义判断：
     - **P0**：严重阻塞，核心流程走不下去、没有绕过办法，或数据丢失；
     - **P1**：明显的 Bug，功能结果不对、用户一眼能看出来；
     - **P2**：非核心功能的问题，或体验、展示上的小问题。

     对照描述能明确落到某一级才自己定；拿不准就在第 5 步建 Task 前问 QA（说明你倾向哪一级、为什么）；QA 说先建时用 `none`。Task 优先级的映射见 [Task 字段](references/report-fields.md#优先级)。
   - **业务模块**：用界面上的功能名称描述问题所在的功能（如「房间-群聊」「任务看板」），不确定时写「待 QA 确认」。

## 2. 准备

确认 `tutti-cli task create --help` 可用（见开头）。当前 Room 就是 Task 要建到的 Room；QA 要求建到别的 Room 时，请 QA 到那个 Room 里重新发起，不跨 Room 创建。

## 3. 采集现场

### 3.1 Web 日志（主 agent，先做）

详见 [Web 日志](references/web-logs.md)。用户给了 WebMCP 连接链接、页面开在本机 Chrome 时，用 `chrome-devtools` MCP：

1. `list_pages` + `list_webmcp_tools` 按链接里的页面与 Account 匹配页面，记下页面 URL（「页面链接」）。
2. `execute_webmcp_tool` 分页读 `get_web_logs`，每页存一个文件，用 `scripts/merge_web_logs.py` 合并成 `$REPORT/web/web-logs.log`。
3. `execute_webmcp_tool` 调 `list_my_computers`（房间相关时加 `list_room_agents`），用于定位 Computer。

不刷新、不跳转页面。WebMCP 不可用、用户在另一台机器上或页面已刷新时，用 QA 导出的诊断包；两者都没有时记为 `pending`，第 5 步请用户导出。

### 3.2 Computer 日志（后台进程）

按 [Computer 定位](references/computer-target.md) 确定设备：优先 Web 日志里故障时间附近记录关联的 Computer，其次页面的 `list_my_computers`，再其次用户说的设备名。确定后立刻放到后台跑，不等它：

```sh
python3 scripts/collect_computer.py --computer-id ID --incident-at <question_time> --output-dir $REPORT/computer > $REPORT/computer.json &
```

有多个候选或没有线索时记为 `pending`，第 5 步请用户确认设备，确认后再跑。

### 3.3 Server 日志（subagent）

拿到 Web 日志后交给一个 subagent（给它下面的命令和输出路径，只让它回传结果 JSON）；不支持 subagent 时用后台进程：

```sh
python3 scripts/collect_server.py --question-time <question_time> \
  --web-logs <web-logs.log 或诊断包 zip> --output-dir $REPORT/server
```

新版 Web 日志的每条 HTTP 记录都带网关的 request id，脚本直接用它们拉全这些请求的日志（看 `request_ids_in_web_logs`、`matched_request_ids`）；旧版 Web 的记录没有 id，脚本把其中失败的请求按 method、路径、状态码、时间对到服务端访问日志，取回 `request_id`（看 `web_requests_matched`）。`--path-contains <房间或 Computer ID>` 会带回整段时间窗的大量请求，只在结果为 `empty` 或需要整段上下文时再加。

结果里的 `namespaces`／`environments` 告诉你环境：`tutti` 是生产，`lane-ppe-*` 是 PPE；`correlated_requests` 中与故障相关的请求和 `web_failures_not_in_server_logs`（页面失败但没到服务端的请求）写进「问题上下文」。详见 [Server 日志](references/server-logs.md)。


## 4. 发布附件

按 [现场材料与附件](references/registration-logs.md)，把 QA 的截图／视频（先复制到 `$REPORT`）和全部日志在一次调用里发布到当前 Room：

```sh
tutti-cli artifact publish --message "Bug 现场：<标题>" --files '[
  {"type":"file","path":"<$REPORT>/web/web-logs.log","name":"Web 日志","description":"提问前 10 分钟的页面日志"},
  {"type":"file","path":"<$REPORT>/server/server-logs.log","name":"Server 日志","description":"tutti-server 相关请求日志"},
  {"type":"file","path":"<$REPORT>/computer/<召回包>.tar.gz","name":"Computer 日志","description":"Computer 日志召回包"},
  {"type":"file","path":"<$REPORT>/screenshot-1.png","name":"截图 1"}
]' --json
```

Computer 召回还没结束时，先发布已有的；召回完成后再发布一次召回包。记下每个附件的名称，写进描述的「附件」段。发布失败时保留文件，写清原因，继续建 Task。

## 5. 建 Task 与收尾

1. 等 Computer 召回完成（读 `$REPORT/computer.json`）并发布召回包。`desktopd.log` 里故障时间附近失败的出站请求带有 Server 日志中没有的 `request_id` 时，用 `collect_server.py --request-id <id> --output-dir $REPORT/server-computer` 补拉并发布（见 [Computer 日志里的 request id](references/computer-logs.md#日志里的-request-id)）。
2. **建 Task 前先把要问的问一次。** Task 建好后不能再用 CLI 修改，所以下表中有任何一项缺口时，先一次列出问题、结束本轮（回复里说明「Task 尚未创建，等你回复后创建」）；用户回复后在同一会话里补采、发布，再建 Task。用户说「先建」或明确不再补充时直接建，缺的写进描述的「待 QA 确认」。没有缺口时直接建。

   | 缺什么 | 怎么请用户提供 |
   |---|---|
   | Web 现场 | 在出问题的 Tutti 页面打开「设置 → 诊断」，点「复制 WebMCP 连接链接」发过来并保持页面不刷新；或在同一浏览器「导出日志」（范围覆盖问题发生时间），把 zip 发过来 |
   | 故障设备 | 从列出的候选（名称、平台、版本）里选当时用的那台；或直接提供设备名称／Computer ID |
   | 优先级（拿不准时） | 「这条按 P1（明显 Bug）登记合适吗？P0 严重阻塞／P1 明显 Bug／P2 非核心 Bug」，附一句判断理由 |
   | 期望（没说清，或现场事实与 QA 的说法不一致时） | 把 QA 的说法和查到的事实并列，请 QA 确认期望，例如「你说是同一份文件，记录里三条内容各不相同：期望只显示最新一份，还是保留历史但标出版本？」 |

   登录过期按上面的规则当场自动恢复，不列在这里；真正的工具缺失、权限不足才写进回复交给维护方，不因此推迟建 Task。
3. 按 [Task 字段](references/report-fields.md) 把描述写到 `$REPORT/description.txt`，建 Task：
   ```sh
   tutti-cli task create --operation-id <operation_id> --title "<标题>" \
     --description "$(cat <$REPORT>/description.txt)" --priority <urgent|high|medium|low|none> --json
   ```
   回执里 `task.taskId` 应等于 `operation_id`。超时或网络错误等结果不确定时，用同一个 `--operation-id` 和相同参数重试；参数校验错误先修正再重试。成功后用 `tutti-cli task show --task-id <operation_id> --json` 回读核对。
4. Task 创建后是未指派、`todo` 状态。请用户在 Tutti 任务看板把它指派给跟进人（附上建议的人）。建好之后用户才补充的内容，在同一会话里补采、发布附件，并请 QA 把新发现补进 Task；不再建第二个 Task。
5. 按开头的自查表逐项确认；全部完成后按 [会话上传](references/session-upload.md) 上传本次会话一次。
6. 最终回复：Task 标题与 ID、所在 Room、优先级、环境、已发布的现场附件、缺失项及需要用户做的事（至少包括指派跟进人）。
