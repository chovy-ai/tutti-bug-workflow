---
name: bug-investigate
description: QA 提 Bug：接收 QA 上报或补充，在飞书登记，固定采集 Web 与 Computer 日志，按需查询 Server 日志，读代码完成根因分析并回填飞书；只有遇到自己无法解决的卡点才向 QA 提问。
---

# QA 提 Bug

你负责把 QA 的一次上报处理到根因分析完成：登记、取证、分析、回填。走到根因是为了确认必要的现场信息都已拿到；不在中途为汇报进度回复 QA。

**无状态。** 本 Skill 与脚本都不在本地保存流程状态。`record_id`、提问时间、采集结果、已问过 QA 的问题都记在本次会话上下文中；对外唯一的事实来源是飞书记录本身。日志、召回包、代码工作区都是本次会话的临时文件，放在会话开始时创建的临时目录（下称 `$TMP`）里，用完即可丢弃。QA 补充信息后再次调用本 Skill 时，从飞书记录读取已有内容继续。

**独立。** 本 Skill 不依赖也不交接给方案、修复场景；只写下文列出的飞书字段。

脚本路径相对插件根目录，均输出一段 JSON。飞书、tutti-ops 的认证与安装缺口由维护方处理（`$tutti-bug-workflow:bug-setup`），不让 QA 处理。已有权限内的日志读取、召回、附件上传与字段回填属于本任务授权，无需逐项再问。

## 1. 接收与建单

1. 从 QA 消息整理：标题、期望与实际表现、复现步骤与频率、环境、发生时间与时区、截图／录屏（实际查看）、WebMCP 连接链接或页面诊断 ID。QA 原话、你已验证的事实、待验证的推断分开记。
2. 固定 `question_time`：触发本次上报的消息时间（含时区的 ISO 8601）；拿不到时用你收到消息的时间并注明近似。本次排查内所有采集窗口都用它。
3. 建单或找回：
   ```sh
   python3 scripts/feishu.py create --title "标题" --description @$TMP/description.md
   ```
   已有同名记录时返回该记录（`action: existing`），不会重复建单。QA 已给出记录链接时直接使用其中的 `record_id`。新记录的流程状态自动为「bug单」。

## 2. 固定采集 Web 与 Computer 日志

两类日志每次都采集，不判断是否需要。采不到就记下原因继续，不为此停下。

**Web**（详见 [WebMCP 日志](../../references/web-logs.md#固定流程提问前-10-分钟--单个-log-附件)）：

- 有连接链接或页面诊断 ID：调用 MCP `tutti-diagnostics.collect_web_logs({connection_url, question_time, output_path: "$TMP/web-logs.log"})`。
- 没有：记为 `{"status": "blocked", "reason": "no_link"}`。

**Computer**（详见 [Computer 定位](../../references/computer-target.md)）：

1. 已知故障设备的 `computerId` 时直接用；否则有 WebMCP 链接时调用 `tutti-diagnostics.list_computer_candidates({connection_url, room_id?})`（截图里有房间名时先用 `list_web_rooms` 找 `roomId`）。
2. 只有一个候选：
   ```sh
   python3 scripts/collect_computer.py --computer-id ID --incident-at <question_time> --output-dir $TMP/computer
   ```
   脚本自动判断本机／远端，远端优先复用已有召回，否则新建并等待完成、下载、校验、解包。
3. 多个候选，或连不上 WebMCP 拿不到候选：记为 `{"status": "pending", "reason": "device_choice", "candidates": [...]}`，留到第 5 步请 QA 选择或提供设备名称／ID。

**上传与现状**：

```sh
python3 scripts/feishu.py attach --record-id REC --file $TMP/web-logs.log --file <召回包>
python3 scripts/check_collection.py --record-id REC --web @$TMP/web.json --computer @$TMP/computer.json
```

只上传日志原件或汇总日志，见 [附件规则](../../references/registration-logs.md#日志文件与附件数量)；过程文件不上传。`check_collection` 只返回现状（各来源状态、文件是否已在飞书上），据此把采集摘要追加到「相关日志」：

```sh
python3 scripts/feishu.py write --record-id REC --append "logs=@$TMP/logs-summary.md"
```

## 3. 分析

1. **代码基线**：`python3 scripts/sync_code.py` 同步 `tutti`、`tutti-server` 最新 main，用返回的 `cache_path` 与 SHA 在 `$TMP/worktrees/` 下建 detached worktree（`git -C CACHE worktree add --detach $TMP/worktrees/tutti SHA`），读取适用的 `AGENTS.md`。用完 `git worktree remove`。见 [固定代码缓存](../../references/repository-cache.md)。
2. **因果链**：从复现入口读代码与测试，按 [业务逻辑、日志与复现路径](../../references/root-cause-analysis.md) 建立 `触发条件 → 首个错误状态 → 后续消费／恢复 → QA 可见现象`，列出候选原因及证实／排除条件，对照已采集的 Web、Computer 日志。
3. **Server 日志由你判断**：链路涉及服务端请求、权限、成员、持久化或投影，且现有证据不能区分候选时，按 [服务端日志](../../references/server-logs.md) 自行决定查询范围与条件，结果汇总为 `$TMP/server-logs.log` 并 `attach`。不涉及或已有证据足够时不查，在排查验证里写一句依据。
4. **验证**：用测试、断点或最小复现验证主复现路径，再检查同一错误状态的其他可达路径，区分「已复现／仅推演／已排除／受阻」。

## 4. 判断根因

满足 [根因完成条件](../../references/root-cause-analysis.md#5-确认根因的完成条件) 才算确认：触发条件与首个错误状态已定位，因果链由现场日志或实际复现支持并能关联本条 Bug 的现场，竞争假设与反例已处理。还有自己能取得的证据或能执行的验证时继续做，不提前停。

## 5. 回填与停下

回填前用 `feishu.py read --record-id REC` 读最新内容；QA 在此期间补充了信息就先纳入分析。按 [字段契约](../../references/report-fields.md) 分字段写，根因字段只写两到四句因果链：

```sh
python3 scripts/feishu.py write --record-id REC \
  --set analysis_conclusion=@$TMP/conclusion.md --set analysis_report=@$TMP/root-cause.md \
  --set investigation_evidence=@$TMP/evidence.md --set code_baselines=@$TMP/baselines.md \
  --set code_references=@$TMP/code-refs.md --append open_items=@$TMP/open-items.md
```

可写字段：`--set` 覆盖 `analysis_conclusion`、`analysis_report`、`investigation_evidence`、`code_baselines`、`code_references`、`suspected_modules`、`ui_only`；`--append` 追加 `logs`、`dialogue`、`open_items`（保留人工内容）。脚本写后回读核对。

**只有遇到自己无法解决的卡点才停下。** 先把不依赖卡点的工作做完；确实推进不下去时，一次列出所有需要 QA 提供的东西，每项说明为什么需要、怎么获取，追加到「QA/RD沟通」并回复 QA。见 [QA 反馈](../../references/qa-dialogue.md)。常见的获取方式：

| 缺什么 | 怎么请 QA 提供 |
|---|---|
| WebMCP 连接链接 | 在 Tutti「设置 → 诊断」点「复制 WebMCP 连接链接」发过来，并保持该页面不要刷新 |
| 页面已刷新、旧日志取不到 | 在「设置 → 诊断」选择覆盖故障时间的范围，点「导出日志」，把文件发过来 |
| 故障设备 | 从列出的候选（名称、平台、在线状态）里选当时用的那台；列不出候选时直接提供设备名称或 Computer ID |
| 现场事实 | 只问 QA 能观察到、且会改变下一项验证的事实，例如操作顺序、是否稳定复现 |

工具、权限、认证问题不问 QA，写进「待核实与阻塞」交给维护方。QA 回复后再次调用本 Skill，读取同一记录继续。

## 6. 结束并上传会话

整体排查结束、根因已确认且字段回填成功后（或用户明确结束本次排查），按 [会话上传](../../references/session-upload.md) 上传本次会话一次。同一会话只上传一次，是否已上传记在会话上下文中。上传失败不影响已完成的排查结果，如实告知。

最终回复 QA：已确认的结论（区分代码复现与现场确认）、飞书记录链接；有未解决的卡点时附上需要 QA 提供的内容。
