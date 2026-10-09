# Computer 定位与采集

提 Bug 时 Computer 日志固定采集。难点在于确定故障发生时用的是哪台 Computer；确定后交给 `scripts/collect_computer.py`。

## 1. 定位目标

按顺序取第一个可用的来源，记下来源：

1. **现场已有的 ID**：同次操作的 Web 日志、请求或任务上下文里的 `computerId`／`agentTargetId`。页面当前选中的 Computer 可能已经变了，不能替代故障时的目标。
2. **页面目录**：有 WebMCP 连接链接时调用插件工具（自动读完全部分页，调用前后核对页面与 Account）：
   - `list_computer_candidates({connection_url, room_id?})`：当前 Account 自有的全部 Computer（含离线）；传 `room_id` 时合并该房间 Agent 背后的 Computer，共享 Agent 的设备只会出现在这里。
   - `list_web_rooms({connection_url})`：按截图里的房间名找 `roomId`。
   - `computerId` 为 null 的条目保留为未知，不从名称推断 ID。离线的 Computer 仍可能是故障目标。
3. **管理端目录**：知道设备名称或所有者时，`tutti-ops computer devices list --name-query NAME --page-all`（见 [tutti-ops CLI](tutti-ops-computer-logs.md#定位目标与已有任务)）。

只有一个候选时直接采集；多个候选或无法列出候选时，记为 `pending`，在给 QA 的问题里请其选择（见第 2 节）。不默认选第一台，也不只看在线设备。

## 2. 请 QA 确认设备

先完成不依赖设备的其他工作，到真正需要时和其他问题一起问。选项用真实返回的显示名称、平台、在线状态或房间线索，ID 只在内部使用：

| 情况 | 话术 |
|---|---|
| 多个候选 | “现有材料还不能确定这次问题发生在哪台设备上。当时用的是〈名称／平台〉中的哪一台？直接回复名称即可。” |
| 列不出候选（没有 WebMCP 链接或调用失败） | “请提供当时在 Tutti 中选择的设备名称或 Computer ID；如果用的是房间里的共享 Agent，提供房间名和 Agent 名称即可。” |
| 需要确认时间 | “请补充大致发生时间和时区，精确到分钟即可。” |

## 3. 采集

```sh
python3 scripts/collect_computer.py --computer-id ID --incident-at <question_time> --output-dir $TMP/computer
```

- **本机**：`tutti-computer status --json` 返回的 `computerId` 与目标一致且配置了 `computer-local.paths` 时，复制这些文件（见 [本地读取](computer-logs.md#本地读取指定文件)）。
- **远端**：优先复用覆盖故障时间的可下载召回，其次加入正在进行的召回，都没有才新建（取能覆盖故障前 10 分钟的最小范围）；等待完成后下载、校验 SHA-256、安全解包。协议见 [远端日志召回](computer-logs.md#远端复用-tutti-日志召回)。
- 输出 JSON 的 `status` 为 `captured`／`partial`／`blocked`，`gaps` 写明覆盖、截断或未知时间戳等缺口，`reason` 写明受阻原因。设备离线、召回超时、权限不足属于维护侧问题，不问 QA。

上传原始召回包，解包目录只用于本地阅读。读日志时核对相关状态事件与请求关联，不只看 error；日志没有 error 不代表没有异常。
