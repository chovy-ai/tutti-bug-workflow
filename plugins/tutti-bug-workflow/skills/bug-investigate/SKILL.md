---
name: bug-investigate
description: QA 提 Bug（「记个 bug」「帮我提个 bug」「登记一下这个问题」等都算）：每次调用都走完全程——在飞书 Bug 管理表登记，固定采集当时的现场日志（Web 页面日志、tutti-server 日志、Computer 日志），把上下文和附件填进表格；不做根因分析，只有遇到自己无法解决的卡点才向用户提问。
---

# QA 提 Bug

你负责把一次上报变成一条**上下文完整**的 Bug 记录，交给 RD 排查：登记、采集当时的全部现场、上传、填字段。**不分析根因，不读代码**；时间花在把现场带全上。

**一旦调用就走完全程。** 「记个 bug」「帮我提个 bug」「登记一下」都执行第 1–5 步，没有「只登记」的模式。建单只是第 2 步，不能回复「已登记」就结束。

**连续执行，一次做完。**

- 每一步做完立刻开始下一步，中途不输出阶段总结，不问「要不要继续」「要不要采集日志」。
- 耗时操作在本轮内等它完成：Computer 远端召回最长约 25 分钟，期间并行做其他步骤，不把控制权交还给用户。
- 某一项卡住时记下原因，继续其他能做的；全部做完或全部卡住才写最终回复。

**尽量并行。** Web 日志先采（它给出 request id 和 Computer 线索），随后三件事同时进行：Computer 召回用后台进程跑，Server 日志交给 subagent 查，主 agent 上传附件、填字段。宿主不支持 subagent 时，Server 也用后台进程跑。

**不脱敏。** 现场日志原样采集、原样上传。

**无状态。** `record_id`、`question_time`、采集结果都记在本次会话上下文中；日志、截图等是放在会话临时目录（下称 `$TMP`）里的临时文件。对外唯一的事实来源是飞书记录。脚本路径相对本 Skill 目录（`skills/bug-investigate/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责，已有权限内的读取、召回、上传与回填属于本任务授权，无需逐项再问。

写最终回复前逐项自查，任何一项没有结果且不是卡点，就回去做完：

| 自查项 | 必须有的结果 |
|---|---|
| 飞书记录 | `record_id`；Bug 描述、状态、问题类型、提交人、记录时间已填；所属端已判断；优先级已按定义填写，或拿不准、已列入待 QA 确认；业务模块是现有选项之一，或对不上、已列入待 QA 确认 |
| 跟进人 | 已写入「指派人」；或已在回复中请用户指定 |
| Web 日志 | `web-logs.log` 或 QA 导出包已上传；或写明缺什么、怎么提供 |
| Server 日志 | `captured`／`empty`／`blocked`（附原因） |
| Computer 日志 | 召回已完成并上传；或写明受阻原因、待用户确认的设备 |
| 附件 | QA 的截图／视频与全部日志都在「截图、视频、日志」，`check_collection` 显示 `attached: true` |
| 上下文字段 | 环境与版本、页面链接、问题上下文已写入并回读 |
| 会话上传 | 全部完成后已上传一次 |

## 1. 接收

1. 从用户消息整理：期望与实际表现、复现步骤与频率、发生时间与时区、操作账号、截图／视频（实际查看）、WebMCP 连接链接、QA 附带的 Web 诊断包、跟进人姓名、用到的设备。用户原话与你的推断分开记。
2. 固定 `question_time`：触发本次上报的消息时间（含时区的 ISO 8601）；拿不到时用收到消息的时间并注明近似。
3. 判断三个分类字段：
   - **所属端**：`新框架一期-Mac`／`新框架一期-Windows`／`新框架一期-Web`，按问题出现的位置判断。
   - **优先级**：用户（QA）给了就照填。没给时按定义判断：
     - **P0**：严重阻塞，核心流程走不下去、没有绕过办法，或数据丢失；
     - **P1**：明显的 Bug，功能结果不对、用户一眼能看出来；
     - **P2**：非核心功能的问题，或体验、展示上的小问题。

     对照描述能明确落到某一级才自己定；**拿不准就问 QA**：建单时先不填优先级，照常走完全程，在第 5 步的待补充项里问（说明你倾向哪一级、为什么），QA 回复后 `write --set priority=…` 补上。P00、P3 只在 QA 明确说了时使用。P2 的记录不在「新框架（一期）」视图里，脚本会提示，照实填写。
   - **业务模块**：只能从现有模块里选一个，**不能自创**。先 `python3 scripts/feishu.py options --field module` 取选项（已去掉历史上被随手加的非正式选项），选最贴近问题所在功能的那一个，原样填写；写入时脚本会拒绝列表外的值。一个都对不上时问 QA 该归哪个模块，不要新建选项，也不要绕过脚本直接用 lark-cli 写这一列。

## 2. 建单

```sh
python3 scripts/feishu.py create --title "房间：顶部名称与左侧选中房间名称不一致" --record-time <question_time> \
  --set platform=新框架一期-Web --set priority=P1 --set module=房间-群聊
python3 scripts/feishu.py assign --record-id REC --name "张三"     # 用户没指定跟进人时省略 --name
```

「Bug 描述」写精简一行「类别：现象」。同名记录已存在时返回它，不重复建单。新记录自动填状态「未解决」、问题类型「bug」、提交人（lark-cli 当前用户）和记录时间。跟进人同名多人、查不到或没指定时不写入，返回候选或常联系的人，留到第 5 步请用户指定。

## 3. 采集现场

### 3.1 Web 日志（主 agent，先做）

详见 [Web 日志](references/web-logs.md)。用户给了 WebMCP 连接链接、页面开在本机 Chrome 时，用 `chrome-devtools` MCP：

1. `list_pages` + `list_webmcp_tools` 按链接里的页面与 Account 匹配页面，记下页面 URL（「页面链接」）。
2. `execute_webmcp_tool` 分页读 `get_web_logs`，每页存一个文件，用 `scripts/merge_web_logs.py` 合并成 `$TMP/web/web-logs.log`。
3. `execute_webmcp_tool` 调 `list_my_computers`（房间相关时加 `list_room_agents`），用于定位 Computer。

不刷新、不跳转页面。WebMCP 不可用、用户在另一台机器上或页面已刷新时，用 QA 导出的诊断包；两者都没有时记为 `pending`，第 5 步请用户导出。

### 3.2 Computer 日志（后台进程）

按 [Computer 定位](references/computer-target.md) 确定设备：优先 Web 日志里故障时间附近记录关联的 Computer，其次页面的 `list_my_computers`，再其次用户说的设备名。确定后立刻放到后台跑，不等它：

```sh
python3 scripts/collect_computer.py --computer-id ID --incident-at <question_time> --output-dir $TMP/computer > $TMP/computer.json &
```

有多个候选或没有线索时记为 `pending`，第 5 步请用户确认设备，确认后再跑。

### 3.3 Server 日志（subagent）

拿到 Web 日志后交给一个 subagent（给它下面的命令和输出路径，只让它回传结果 JSON）；不支持 subagent 时用后台进程：

```sh
python3 scripts/collect_server.py --question-time <question_time> \
  --web-logs <web-logs.log 或诊断包 zip> [--path-contains <房间或 Computer ID>] \
  --output-dir $TMP/server
```

结果里的 `namespaces`／`environments` 告诉你环境：`tutti` 是生产，`lane-ppe-*` 是 PPE。详见 [Server 日志](references/server-logs.md)。

## 4. 上传与填字段

1. 上传附件（同名同大小的不重复传）：
   ```sh
   python3 scripts/feishu.py attach --record-id REC --file <QA 的截图／视频> --file <web-logs.log 或诊断包> \
     --file $TMP/server/server-logs.log
   ```
2. 按 [字段规则](references/report-fields.md) 写三个上下文字段：
   ```sh
   python3 scripts/feishu.py write --record-id REC --set page_url=<页面链接> \
     --set env_version=@$TMP/env-version.md --set context=@$TMP/context.md
   ```
   - **环境与版本**：环境（生产／PPE／本地开发）与标识（页面域名、Server namespace 如 `lane-ppe-cloud-0928`），Web、tutti-server、Computer 版本与浏览器。
   - **页面链接**：出问题页面的完整 URL。
   - **问题上下文**：期望、实际、复现步骤、频率、发生时间（精确到分钟，含时区）、操作账号；关联 ID：账号、房间、页面会话、Computer、Agent、关键 request id、召回任务 ID。
3. `python3 scripts/check_collection.py --record-id REC --web @$TMP/web.json --computer @$TMP/computer.json` 核对附件。

## 5. 收尾

1. 等 Computer 召回完成（读 `$TMP/computer.json`），上传召回包，把召回任务 ID 补进「问题上下文」，再跑一次 `check_collection`。
2. 需要用户提供的东西一次列出，每项说明怎么获取：

   | 缺什么 | 怎么请用户提供 |
   |---|---|
   | Web 现场 | 在出问题的 Tutti 页面打开「设置 → 诊断」，点「复制 WebMCP 连接链接」发过来并保持页面不刷新；或在同一浏览器「导出日志」（范围覆盖问题发生时间），把 zip 发过来 |
   | 故障设备 | 从列出的候选（名称、平台、版本）里选当时用的那台；或直接提供设备名称／Computer ID |
   | 跟进人 | 「这条 Bug 由谁跟进？直接回复名字即可」，可附上常联系的人；同名多人时列出姓名与部门请用户选 |
   | 优先级（拿不准时） | 「这条按 P1（明显 Bug）登记合适吗？P0 严重阻塞／P1 明显 Bug／P2 非核心 Bug」，附一句判断理由 |
   | 业务模块（对不上时） | 列出两三个最接近的现有模块请 QA 选，不新建选项 |

   工具、权限、认证问题不问用户，写在回复里交给维护方。用户补充后再次调用本 Skill，读取同一记录继续。
3. 按开头的自查表逐项确认；全部完成后按 [会话上传](references/session-upload.md) 上传本次会话一次。
4. 最终回复：飞书记录链接、环境、已采集的现场与附件、缺失项及需要用户提供的内容。
