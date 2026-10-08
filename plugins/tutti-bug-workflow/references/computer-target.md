# Computer 定位与 QA 询问

需要判断是否采集 Computer 日志、定位操作目标或消歧候选时读取本页。2026-09-30 从 tutti 最新远端 main `5a205b6dd8ed4f7e5b490629601a3253d11626db` 的独立 worktree 核对了目录工具与本机状态输出；现场版本和浏览器桥另行确认。

## 1. 判断日志用途

根据问题描述、已有日志及相关代码标记 desktopd 日志的用途与依据：

- **必需**：首个异常或待验证边界涉及 Computer 上的安装、配置／授权执行、命令或工具执行、文件访问、Agent 执行、连接、状态同步、进程或 VM 生命周期，已有证据无法区分相关候选。
- **补充**：首个现象可在 Web 解释，但同一次操作的 Computer 执行结果、返回时序或状态差异仍可能改变根因判断。
- **无需采集**：代码与现场证据支持来源不参与该错误，或已关联现场的替代证据足够。前者标记不适用并写明因果边界；后者保留来源相关性，记录无需追加及已有证据，不强制召回。
- **待判断**：现有材料不足以确定参与链路或目标；先继续独立分析，不能用工具不可用或设备离线代替不适用判断。

每轮记录必要程度、候选原因、缺失观察、期望日志内容和取得证据后的验证动作，并按 [登记清单](registration-logs.md#保存证据与采集结果) 将判断与采集状态分别保存。初始材料不足时先取得可用 Web 证据，再定位涉及的 Computer。登记的两类来源都检查，但采集和上传按实际用途和关联结果选择。不能把“安装连接器”字样本身等同于 desktopd 是根因，也不能用本地 UI 最小复现代替原现场的跨端关联。

来源按本轮代码的实际写入链路选择，可能涉及 desktopd、Companion、runtime-host 或执行诊断，见 [Computer 日志获取](computer-logs.md)。先复用已有日志与召回包，只补时间或状态覆盖缺口；没有 error 不表示没有异常，必须核对相关状态事件、请求关联及留存范围。

## 2. 查询真实候选

优先采用发生问题那次请求、日志或操作上下文中的 `computerId`／`agentTargetId`，记录来源、时间和环境。页面当前选中的 Computer 可能已变化，不替换故障时的目标。

缺少明确 ID 时，在已授权且匹配现场 Account 的浏览器桥中发现并调用下列原生工具。传入参数按实际 schema，名称、URL 和截图只作为线索。

| 工具 | 参数 | 可用于定位的返回 |
|---|---|---|
| `list_my_computers` | `limit?`、`cursor?` | 当前账号自有 Computer 的 `computerId`、`displayName`、`platform`、`connectionStatus` 及已安装 Agent 摘要 |
| `list_rooms` | `limit?`、`cursor?` | 可见房间的 `roomId`、名称、公开属性 |
| `list_room_agents` | `roomId` 必填，`limit?`、`cursor?` | 房间 Agent 的 `agentTargetId`、ownership、executionAvailability，以及授权可见的 `computer.computerId`、名称、online |

共享 Agent 的 Computer 可能不在 `list_my_computers` 中；有相关房间线索时用房间 Agent 目录核对。返回的 Computer ID 为 null 时保留缺口，不从 Agent 名称构造 ID。Computer 在线状态与 Agent 可执行状态分别使用，离线 Computer 仍可能是故障目标。

这些工具只读目录，不读取 desktopd 文件、不返回故障时选中的 Computer，也不提供远端日志授权。相同页面的返回须核对 `pageSessionId`、Account 与 `observedAt`。分页遵循实际 `nextCursor`：默认 50、最大 200；当前游标 60 秒过期，限定工具、账号、查询与页大小。过期或目录变化时重新查询并保存新结果，不把第一页当作全部候选。

WebMCP 工具尚未部署、未授权或浏览器桥缺失时，按 [Web 接入引导](web-logs.md#识别或调用失败时的处理) 记录缺口。已有管理环境和权限时，可用 [tutti-ops 设备查询](tutti-ops-computer-logs.md#定位目标与已有任务) 根据用户和名称取得候选；两种方式的身份与数据范围分别记录。

## 3. 仅询问必要信息

先完成本轮可自行进行的代码与证据分析，满足 [QA 追问前的完成条件](qa-dialogue.md#追问前的完成条件)。只有具体假设的验证确需目标设备、且现有材料与实际查询仍不能确定时，才询问 QA。候选选项使用真实返回的显示名称、平台或房间线索，ID 与技术状态保存在内部定位记录；QA 明确选择后绑定目标。

| 缺口 | 面向 QA 的提示词 |
|---|---|
| 验证必须区分所选设备，但材料和查询未能确定 | “为了确认是否只发生在这台设备上，请补充当时在 Tutti 中选择的设备名称；如果使用共享 Agent，提供房间和 Agent 名称即可。” |
| 查询返回多个相关候选 | “现有材料还不能确定这次安装对应哪台设备。当时选的是〈实际名称／平台／房间线索〉中的哪一台？直接选择名称即可。” |
| 本机线索仍不能与故障操作关联 | “为了确认问题是否与所选设备有关，请确认：当时选的是正在使用的这台电脑，还是 Tutti 里的另一台设备？” |
| 目录入口缺失 | 保存维护侧接入阻塞，继续独立分析；按具体假设判断是否需要上面的现场设备问题 |
| 确认故障时间后才能验证某次操作 | “为了确认这次安装的先后顺序，请补充大致发生时间和所在时区，精确到分钟即可。” |

一次集中询问当前必要的信息，记录 QA 回答、候选列表与选择来源。入口权限缺失交给接入维护方，凭证通过 CLI 或宿主的认证入口提供。

## 4. 核对本地或远端并交接

需要判断是否为本机时，先发现实际 `tutti-computer` 命令，按其帮助执行只读 `tutti-computer status --json`，从实际返回取得 `computerId`、bindingRevision、computerVersion 和连接状态；命令或状态不可用时保留身份核对缺口，不触发 setup、绑定或重启。只有目标 ID 与本机已绑定 ID、环境一致时读取配置中的本地文件。用户明确表示本机但无法读到 ID 时，继续核对其他可信绑定证据，记录依据。

目标为远端时，用已确认的 `computerId` 进入 [Tutti 日志召回](computer-logs.md#远端复用-tutti-日志召回)，检查实际环境与权限。目录可见、拥有或共享 Agent 不证明拥有日志召回权限。

完成条件：日志用途有依据，目标唯一且有来源引用，本机／远端路由可核对；或已记录必要问题及具体入口缺口。向采集阶段交接 ID、环境、故障时间、版本、关联请求／Agent、定位证据和待补项。

源码核对入口：`docs/architecture/web-mcp.md`、`apps/web/src/renderer/src/modules/web-mcp/application/webMcpCatalogService.ts`（tools、read、parse）、`apps/tutti-computer-cli/internal/app/status_output.go`（localStatusOutput）。目录的组合、分页与授权场景测试见 `apps/web/src/renderer/src/app/bootstrap/webMcpCatalogs.spec.ts`；本次只阅读，没有执行浏览器 E2E。
