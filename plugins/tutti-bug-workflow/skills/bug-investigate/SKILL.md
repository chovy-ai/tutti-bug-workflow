---
name: bug-investigate
description: QA 提 Bug（「记个 bug」「帮我提个 bug」「登记一下这个问题」等都算）：每次调用都走完全程——飞书登记、采集 Web 日志（本机 WebMCP 优先，否则用 QA 导出的诊断包）与 Computer 日志、按需查询 Server 日志、读代码分析到根因并回填飞书；没有只登记的模式，只有遇到自己无法解决的卡点才停下向 QA 提问。
---

# QA 提 Bug

你负责把 QA 的一次上报处理到根因分析完成：登记、取证、分析、回填。走到根因是为了确认必要的现场信息都已拿到；不在中途为汇报进度回复 QA。

**一旦调用就走完全程。** 「记个 bug」「帮我提个 bug」「登记一下」与「帮我查一下」完全等价，都执行第 1–6 步；不存在「只登记」「只补附件」的模式。建单成功只是第 1 步，不能在此回复「已登记」后结束。只有遇到第 5 步所说的、自己无法解决的卡点，才停下来向 QA 提问。

**连续执行，一次做完。**

- 每一步做完立刻开始下一步。中途不输出阶段总结，不问「要不要继续」「要不要采集日志」「要不要开始分析」，不等用户确认。
- 耗时操作在本轮内等它完成：远端召回最长约 25 分钟、代码同步、测试与复现都等结果出来再往下走，不因为耗时就把控制权交还给用户。
- 某一项卡住时，记下原因，跳过它继续其他能做的步骤；所有步骤都做完或都卡住了，才写最终回复。
- 写最终回复前逐项自查，任何一项没有结果且不是卡点，就回去把它做完：

  | 自查项 | 必须有的结果 |
  |---|---|
  | 飞书记录 | `record_id` 已建或已找回，提出人已填 |
  | 跟进人 | 已写入；或已在回复中请用户指定 |
  | Web 日志 | `captured`／`partial`，或 `pending` 并写明缺什么 |
  | Computer 日志 | `captured`／`partial`／`blocked`，或 `pending` 并写明缺什么 |
  | 附件 | 已上传，`check_collection` 显示 `attached: true` |
  | 代码 | 两个仓库已同步并读过相关代码 |
  | 根因 | 已确认；或已排查到底仍无法确定，写明已排除的、仍成立的候选和无法推进的原因；回复里没有留给别人做的「下一步」 |
  | 飞书字段 | 结论、根因、排查验证、代码基线、相关代码已写入并回读 |
  | 会话上传 | 根因确认时已上传一次 |

**无状态。** 本 Skill 与脚本都不在本地保存流程状态。`record_id`、提问时间、采集结果、已问过 QA 的问题都记在本次会话上下文中；对外唯一的事实来源是飞书记录本身。日志、召回包、代码工作区都是本次会话的临时文件，放在会话开始时创建的临时目录（下称 `$TMP`）里，用完即可丢弃。QA 补充信息后再次调用本 Skill 时，从飞书记录读取已有内容继续。

**独立。** 本 Skill 不依赖也不交接给方案、修复场景；只写下文列出的飞书字段。

脚本路径相对本 Skill 目录（`skills/bug-investigate/`），均输出一段 JSON。飞书、tutti-ops 的认证与安装缺口由维护方处理（`$tutti-bug-workflow:bug-setup`），不让 QA 处理。已有权限内的日志读取、召回、附件上传与字段回填属于本任务授权，无需逐项再问。

## 1. 接收与建单

1. 从 QA 消息整理：标题、期望与实际表现、复现步骤与频率、环境、发生时间与时区、截图／录屏（实际查看）、WebMCP 连接链接、QA 附带的 Web 诊断包（`tutti-web-diagnostics-*.zip`）、用户指定的跟进人姓名（如「跟进人：张三」）。QA 原话、你已验证的事实、待验证的推断分开记。
2. 固定 `question_time`：触发本次上报的消息时间（含时区的 ISO 8601）；拿不到时用你收到消息的时间并注明近似。本次排查内所有采集窗口都用它。
3. 建单或找回：
   ```sh
   python3 scripts/feishu.py create --title "标题" --description @$TMP/description.md
   ```
   已有同名记录时返回该记录（`action: existing`），不会重复建单。QA 已给出记录链接时直接使用其中的 `record_id`。新记录的流程状态自动为「bug单」，提出人自动填为 lark-cli 当前登录用户。
4. 跟进人：
   ```sh
   python3 scripts/feishu.py assign --record-id REC --name "张三"   # 用户没指定时省略 --name
   ```
   只匹配到一人时写入并回读确认（`status: assigned`）。同名多人（`ambiguous`）、查不到（`not_found`）或用户没指定（`missing`）时不写入，返回候选或当前组织里常联系的人（`suggestions`），留到第 5 步请用户指定；不为此停下。也可以用 `feishu.py suggest-users --query 关键字` 按名字在组织里查人。

建单后不回复 QA，直接进入第 2 步。

## 2. 固定采集 Web 与 Computer 日志

两类日志每次都采集，不判断是否需要。采不到就记下原因继续，不为此停下。

**Web**（详见 [Web 日志](references/web-logs.md)），按顺序取第一个可用的：

1. **本机 WebMCP**：QA 给了连接链接、页面开在本机 Chrome 时，用 `chrome-devtools` 的 `list_pages` → `list_webmcp_tools` 匹配页面，`execute_webmcp_tool` 分页读 `get_web_logs`，再用 `scripts/merge_web_logs.py` 合并成 `$TMP/web/web-logs.log`。不刷新、不跳转 QA 的页面。
2. **QA 导出的诊断包**：QA 发来的 zip 原样上传，再解包到 `$TMP/web/` 阅读；包已附在飞书记录上时用 `python3 scripts/feishu.py download --record-id REC --name <文件名> --output-dir $TMP/web` 取到本地，不重复上传。
3. 都没有：记为 `{"status": "pending", "reason": "no_export"}`，留到第 5 步请 QA 导出。

**Computer**（详见 [Computer 定位](references/computer-target.md)）：

1. 定位故障设备：优先用 Web 日志里故障时间附近记录关联的 Computer（WebMCP 日志记录或诊断包 `manifest.computers[]`／`computerRefs`）；WebMCP 可用时还可调用页面的 `list_my_computers`／`list_room_agents` 列出候选；都没有时用 QA 提供的设备名称或 ID，经 `tutti-ops computer devices list --name-query` 查到 `computerId`。
2. 只有一个候选：
   ```sh
   python3 scripts/collect_computer.py --computer-id ID --incident-at <question_time> --output-dir $TMP/computer
   ```
   脚本自动判断本机／远端，远端优先复用已有召回，否则新建并等待完成、下载、校验、解包。
3. 多个候选，或没有任何线索：记为 `{"status": "pending", "reason": "device_choice", "candidates": [...]}`，留到第 5 步请 QA 选择或提供设备名称／ID。

**上传与现状**：

```sh
python3 scripts/feishu.py attach --record-id REC --file <web-logs.log 或 Web 诊断包> --file <召回包>
python3 scripts/check_collection.py --record-id REC --web @$TMP/web.json --computer @$TMP/computer.json
```

只上传日志原件或汇总日志，见 [附件规则](references/registration-logs.md#日志文件与附件数量)；过程文件不上传。`check_collection` 只返回现状（各来源状态、文件是否已在飞书上），据此把采集摘要追加到「相关日志」：

```sh
python3 scripts/feishu.py write --record-id REC --append "logs=@$TMP/logs-summary.md"
```

## 3. 分析

1. **代码基线**：`python3 scripts/sync_code.py` 同步 `tutti`、`tutti-server` 最新 main，用返回的 `cache_path` 与 SHA 在 `$TMP/worktrees/` 下建 detached worktree（`git -C CACHE worktree add --detach $TMP/worktrees/tutti SHA`），读取适用的 `AGENTS.md`。用完 `git worktree remove`。见 [固定代码缓存](references/repository-cache.md)。
2. **因果链**：从复现入口读代码与测试，按 [业务逻辑、日志与复现路径](references/root-cause-analysis.md) 建立 `触发条件 → 首个错误状态 → 后续消费／恢复 → QA 可见现象`，列出候选原因及证实／排除条件，对照已采集的 Web、Computer 日志。
3. **Server 日志由你判断**：链路涉及服务端请求、权限、成员、持久化或投影，且现有证据不能区分候选时，按 [服务端日志](references/server-logs.md) 自行决定查询范围与条件，结果汇总为 `$TMP/server-logs.log` 并 `attach`。不涉及或已有证据足够时不查，在排查验证里写一句依据。
4. **验证**：用测试、断点或最小复现验证主复现路径，再检查同一错误状态的其他可达路径，区分「已复现／仅推演／已排除／受阻」。

## 4. 排查到底，判断根因

**排查到底。** 分析中想到的「下一步应该核对 X」「如果发现 Y 再查 Z」，只要你自己能做——读代码、对比接口返回与页面显示、查 Server 日志、写最小复现、跑测试、只读查看页面——就现在做，用结果推进，不写进回复留给别人。条件式的「如果……再查」立刻去查，用结果决定下一步。

满足 [根因完成条件](references/root-cause-analysis.md#5-确认根因的完成条件) 才算确认：触发条件与首个错误状态已定位，因果链由现场日志或实际复现支持并能关联本条 Bug 的现场，竞争假设与反例已处理。

**排查到底仍无法确定时，反馈但不阻塞。** 自己能做的验证都做完、仍有无法区分的候选时，结论写「原因未确认」，并写清：

- 已经排除了什么、依据是什么；
- 仍成立的候选，各自的证据和还缺的那一项观察；
- 为什么无法再推进：缺只有 QA 能提供的现场信息、缺权限、现场已无法复现等。

然后照常完成第 5、6 步：回填全部字段、上传附件、按需向 QA 提问。「原因未确认」是如实的结论，不是停下的理由。

回复里不出现你自己能做却没做的事，例如「下一步应核对……」「建议再查……」「如有需要我可以……」；出现了就说明还没排查到底，回去做完。

## 5. 回填与停下

回填前用 `feishu.py read --record-id REC` 读最新内容；QA 在此期间补充了信息就先纳入分析。按 [字段契约](references/report-fields.md) 分字段写，根因字段只写两到四句因果链：

```sh
python3 scripts/feishu.py write --record-id REC \
  --set analysis_conclusion=@$TMP/conclusion.md --set analysis_report=@$TMP/root-cause.md \
  --set investigation_evidence=@$TMP/evidence.md --set code_baselines=@$TMP/baselines.md \
  --set code_references=@$TMP/code-refs.md --append open_items=@$TMP/open-items.md
```

可写字段：`--set` 覆盖 `analysis_conclusion`、`analysis_report`、`investigation_evidence`、`code_baselines`、`code_references`、`suspected_modules`、`ui_only`；`--append` 追加 `logs`、`dialogue`、`open_items`（保留人工内容）。脚本写后回读核对。

**只有遇到自己无法解决的卡点才停下。** 先把不依赖卡点的工作做完；确实推进不下去时，一次列出所有需要 QA 提供的东西，每项说明为什么需要、怎么获取，追加到「QA/RD沟通」并回复 QA。见 [QA 反馈](references/qa-dialogue.md)。常见的获取方式：

| 缺什么 | 怎么请 QA 提供 |
|---|---|
| Web 诊断包 | 在出问题的那个浏览器、同一账号下打开 Tutti「设置 → 诊断」，「导出范围」选能覆盖问题发生时间的一档（例如最近 1 小时），点「导出日志」，把下载的 zip 发过来 |
| 故障设备 | 从列出的候选（名称、平台、版本）里选当时用的那台；列不出候选时直接提供设备名称或 Computer ID |
| 跟进人 | 未指定：「这条 Bug 由谁跟进？直接回复名字即可」，可附上 `suggestions` 里的几个常联系的人；同名多人：列出候选的姓名与部门，请用户选一位 |
| 现场事实 | 只问 QA 能观察到、且会改变下一项验证的事实，例如操作顺序、是否稳定复现 |

工具、权限、认证问题不问 QA，写进「待核实与阻塞」交给维护方。QA 回复后再次调用本 Skill，读取同一记录继续。

## 6. 结束并上传会话

排查结束且字段回填成功后，按 [会话上传](references/session-upload.md) 上传本次会话一次。排查结束指：根因已确认；或已排查到底仍无法确定、且不再等待 QA 补充；或用户明确结束本次排查。同一会话只上传一次，是否已上传记在会话上下文中。上传失败不影响已完成的排查结果，如实告知。

最终回复 QA：结论（已确认，区分代码复现与现场确认；或原因未确认及已排除与仍成立的候选）、飞书记录链接；需要 QA 提供的内容逐项写明怎么获取。不写「下一步应……」这类你自己能做的事。
