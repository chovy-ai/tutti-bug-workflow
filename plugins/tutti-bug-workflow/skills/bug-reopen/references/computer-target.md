# Computer 定位与采集

验收打回时 Computer 日志固定采集。难点在于确定验收时用的是哪台 Computer（不一定是当初提 Bug 的那台）；确定后交给 `scripts/collect_computer.py`。

## 1. 定位目标

按顺序取第一个可用的来源，记下来源：

1. **Web 诊断包**：`manifest.json` 的 `computers[]` 列出这段时间页面关联过的 Computer（`computerId`、`platform`、`arch`、`computerVersion`）；故障时间附近记录的 `computerRefs` 指向 `manifest.computerContexts[].ref`，能缩小到同一次操作涉及的那台。页面当前选中的 Computer 可能已经变了，以故障时间附近的记录为准。
2. **页面目录（WebMCP 可用时）**：用同一个页面的 `execute_webmcp_tool` 调用 `list_my_computers`（当前 Account 自有的全部 Computer，含离线与名称）、`list_rooms`、`list_room_agents({roomId})`（房间里共享 Agent 背后的 Computer）。按返回的 `nextCursor` 读完全部分页，游标 60 秒过期；`computerId` 为 null 的条目保留为未知，不从名称推断。
3. **QA 提供的设备名称或 ID**：用 `tutti-ops --admin-url https://admin.tutti.sh --mode read computer devices list --name-query NAME --page-all` 查到 `computerId`（见 [tutti-ops CLI](tutti-ops-computer-logs.md#定位目标与已有任务)）。
4. **展示名称**：诊断包里只有 ID，没有设备名称。需要让 QA 选择时，用 `tutti-ops ... computer devices get --computer-id ID` 取 `displayName`、`platform`、在线状态，再列给 QA。

只有一个候选时直接采集；多个候选或没有任何线索时，记为 `pending`，在给 QA 的问题里请其选择（见第 2 节）。不默认选第一台，也不只看在线设备；离线的 Computer 仍可能是故障目标。

## 2. 请 QA 确认设备

先完成不依赖设备的其他工作，到真正需要时和其他问题一起问。选项用设备名称、平台、版本，ID 只在内部使用：

| 情况 | 话术 |
|---|---|
| 多个候选 | “现有材料还不能确定这次问题发生在哪台设备上。当时用的是〈名称／平台〉中的哪一台？直接回复名称即可。” |
| 没有线索（没有诊断包，也没提到设备） | “请提供当时在 Tutti 中选择的设备名称或 Computer ID；如果用的是房间里的共享 Agent，提供房间名和 Agent 名称即可。” |
| 需要确认时间 | “请补充大致发生时间和时区，精确到分钟即可。” |

## 3. 采集

```sh
python3 scripts/collect_computer.py --computer-id ID --incident-at <incident_at> --question-time <question_time> --output-dir $REPORT/computer
```

- **本机**：`tutti-computer status --json` 返回的 `computerId` 与目标一致且配置了 `computer-local.paths` 时，复制这些文件（见 [本地读取](computer-logs.md#本地读取指定文件)）。
- **远端**：优先复用覆盖故障时间的可下载召回，其次加入正在进行的召回，都没有才新建（取能覆盖故障前 10 分钟到后 5 分钟、截止不晚于 `question_time` 的最小范围）；等待完成后下载、校验 SHA-256、安全解包。协议见 [远端日志召回](computer-logs.md#远端复用-tutti-日志召回)。
- 输出 JSON 的 `status` 为 `captured`／`partial`／`blocked`，`gaps` 写明覆盖、截断或未知时间戳等缺口，`reason` 写明受阻原因。本机采集会读每个文件的首末时间（`first_at`／`last_at`／`coverage`），只有全部配置文件都存在且完整覆盖故障前 10 分钟到后 5 分钟（截止不晚于 `question_time`）才算 `captured`；任何文件缺失、时间未知或覆盖不足（日志已轮转、那时没写）时都是 `partial`，改用 `--source remote` 再跑一次走远端召回，两次的文件都挂上。设备离线、召回超时、权限不足属于维护侧问题，不问 QA。

上传原始召回包，解包目录只用于本地阅读。读日志时核对相关状态事件与请求关联，不只看 error；日志没有 error 不代表没有异常。
