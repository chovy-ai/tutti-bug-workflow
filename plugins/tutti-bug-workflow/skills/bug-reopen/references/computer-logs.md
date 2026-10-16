# Computer 日志获取

验收打回时以下本地读取与远端召回都由 `scripts/collect_computer.py` 执行（见 [Computer 定位与采集](computer-target.md#3-采集)）；本页说明它依据的路径与协议。

先按 [Computer 定位与 QA 询问](computer-target.md) 判断日志用途、查询真实候选并核对目标，再选择本地或远端来源，保存 computerId、发生环境、时间与时区及版本。执行机器上的日志只有在目标身份一致时才可作为现场证据。

保存与上传统一按 [评论附件](reopen-comment.md#评论附件)：召回直接取得的原始日志包校验、读取后原样上传，不同时上传拆出的组件文件、摘录和清单；直接取得多个日志文件或已确认的本地日志文件时保留原文件。原文件无法取得、只读接口逐条返回日志内容时，把相关组件、轮转与补采内容按时间合并为一个 `computer-logs.log`，保留来源与多行事件。仍需在本地解包、检索和关联业务链；减少附件不减少上下文核验。

## 本地：读取指定文件

`computer-local.paths` 保存用户或项目维护人指定的文件路径，可配置一个或多个文件。支持绝对路径、`~/`（执行用户的主目录）、`${TMPDIR}/` 和 `${TEMP}/`（明确指定的临时目录环境变量）。配置与介绍不写入个人用户名或机器专属临时目录。读取前使用 `scripts/common.py` 的 `resolve_log_path` 将配置项解析为执行机器上的绝对路径；变量缺失或其值不是绝对目录时记录配置缺口，不替换为猜测目录。只读这些明确指定的文件，按问题时间和定位标识筛选，保留堆栈等相邻上下文；需要轮转日志或其他组件文件时取得相应明确路径后补充配置。以下是默认 state root 的本机场景写法：

```json
{
  "name": "computer-local",
  "kind": "computer",
  "transport": "files",
  "environment": "execution_host",
  "paths": [
    "~/.tutti-amp/computer/logs/companion.log",
    "~/.tutti-amp/computer/logs/desktopd.log",
    "~/.tutti-amp/computer/logs/runtime-host.log",
    "${TMPDIR}/tutti-codex-appserver-startup.jsonl"
  ],
  "scope": "execution_host_only"
}
```

分发配置默认 `paths` 为空，表示待配置；不从 Tutti 默认目录、未指定的环境变量或当前工作目录推导替代文件。上面的临时诊断项适用于已确认设置 `TMPDIR` 的 macOS；Windows 可在确认后使用 `${TEMP}/`。路径不存在、不可读或日志覆盖不足时分别记录具体缺口，不能把它们当成没有错误。完成后将必要片段保存到 Bug 的 `evidence/`，记录实际解析的路径、目标、读取范围和实际覆盖时间。

只有旧配置未包含 `paths` 时，辅助脚本兼容 `root` / `root_env` / `default_root` 与 `relative_paths`；迁移时把已确认属于目标 Computer 的实际路径写入 `paths`。明确路径存在时始终采用它们。

### 已核实的本机场景

2026-09-30 从 `tutti` 最新远端 main `e05e55056ea380580118b988b73b74573a79fc41` 的独立 worktree 核实了以下写入链路，并确认当前 Mac 使用默认 state root、三个主日志和临时诊断文件均存在。用户已确认将此结论用于本机场景；本机配置以 `~/` 和 `${TMPDIR}/` 保存已确认的入口，不固化用户名或机器专属临时目录，分发配置仍保留空 `paths`。其他 Computer 需重新确认目标、安装版本、运行 state root 和实际文件。

Computer 启动时的 state root 优先级是 `--state-root` → `TUTTI_STATE_HOME` → `~/.tutti-amp`。开发态与生产态均使用 `<state-root>/computer/logs/`；源码 worktree 位置不决定运行日志位置。

| 来源 | 文件位置 | 用途 |
|---|---|---|
| Companion | `<state-root>/computer/logs/companion.log` | Computer 绑定、启动、更新与 desktopd 进程管理；macOS 服务的 stdout/stderr 也写入此文件 |
| desktopd | `<state-root>/computer/logs/desktopd.log` | 本地能力、Agent 执行协调、状态跃迁与错误 |
| runtime-host | `<state-root>/computer/logs/runtime-host.log` | runtime-host stdout/stderr、VM 生命周期；macOS 的 VM 串口控制台输出也汇入此文件 |
| Codex 启动诊断 | `os.TempDir()/tutti-codex-appserver-startup.jsonl` | Tutti 内 Codex app-server 的启动、调用和相关诊断；不属于源码目录，也不应在 macOS 上固定写成 `/tmp` |
| VM 崩溃报告 | `<state-root>/computer/bindings/<computerId>/<bindingRevision>/logs/crash-reports/vm-crash-*.txt` | 当前受管启动链路下的 VM 崩溃现场；本机核实存在三份报告 |

轮转文件位于主日志所在目录，名称形如 `desktopd.YYYY-MM-DD.log`、`desktopd.YYYY-MM-DD.N.log`，其他两个组件同理。读取当前主文件不足以覆盖历史故障；需要相关轮转文件时，先取得并记录其明确绝对路径，再按报错时间筛选。日志写入器默认单文件 50 MiB、备份上限 10、保留上限 14 天，目录轮转预算 300 MiB；这些是可配置上限，不保证实际覆盖整个窗口。

崩溃报告的路径必须沿启动环境确认：Companion 将 desktopd 的 `TUTTI_STATE_HOME` 设为绑定目录，runtime-host 继承该 state home，再在其 `logs/crash-reports/` 写报告。当前 `tutti-computer logs export` 却扫描顶层 `<state-root>/logs/crash-reports/`，可能漏收绑定目录下的报告。若导出包未包含报告，单独核对已确认目标的绑定目录，不能据此判断 VM 没有崩溃。不要为了采集日志重启、切换或升级 Computer。

Windows 另有 `<state-root>/computer/logs/companion.stderr.log`，以及 `%ProgramData%\\Tutti\\Runtime VM\\logs\\vm-service.log` 和同目录的 `<VM-ID>.serial.log`。这些是 Windows 分支，不作为当前 Mac 的读取入口。`tutti-guest-agent.log` 在支持包的允许清单中，但当前 Mac 的宿主日志目录未发现该独立文件；不能仅凭清单认定它存在。

源码核对入口：`apps/tutti-computer-cli/internal/app/{app.go,service_logging.go,support_bundle_sources.go}`、`apps/tutti-computer-cli/internal/companion/{process_factory.go,user_service_darwin.go}`、`core/runtime/{runtime_host_connector_unix.go,runtime_host_process.go}`、`runtime/runtime-host/src/{state_paths.h,vm/crash_report.cpp,vm/darwin/virtualization_vm.mm}`、`core/agent/daemon/runtime/codex_appserver_startup_trace.go`。Windows 写入入口是 `cmd/tutti-runtime-vm-service/main_windows.go` 与 `apps/tutti-computer-cli/internal/app/service_console_windows.go`。升级后涉及此链路的问题需对本轮固定 main 和现场版本重新核实。

## 远端：复用 Tutti 日志召回

`computer-remote.acquisition` 固定为 `tutti-runtime-log-recall`。可通过 [tutti-ops CLI](tutti-ops-computer-logs.md) 的 Computer 召回入口，或后续接入的实际 MCP 执行下列服务端协议。CLI 优先复用可下载的历史任务，并提供创建、查询和生成下载链接的入口；完整获取还需下载、校验和读取。MCP 的名称、参数和返回值须以实际 schema 为准，不把普通日志查询工具当成已实现召回。凭证留在宿主或工具的认证存储中。

开始前从本轮固定的最新 main 核对协议与目标环境支持的版本：

- tutti-server：`api/sandbox/v2/computer_runtime_log.proto`、`internal/biz/computer_runtime_log.go`。
- tutti：`services/desktopd/modules/computer/internal/runtimelog/service/service.go` 及 `adapter/archive_collector.go`。

以下是服务端路由；通过网关 API origin 调用时在前面加 `/api/desktop`，tutti-ops 已在请求路径中包含此网关前缀：

| 操作 | 接口 |
|---|---|
| 定位 Computer（已有 ID 时可跳过列表） | `GET /v2/admin/tutti-v2/computers` |
| 创建召回任务 | `POST /v2/admin/tutti-v2/computers/{computerId}/runtime-log-recalls` |
| 查询任务 | `GET /v2/admin/tutti-v2/computers/{computerId}/runtime-log-recalls/{taskId}` |
| 生成下载链接 | `POST /v2/admin/tutti-v2/computers/{computerId}/runtime-log-recalls/{taskId}:create-download-url` |

1. 确认实际服务环境、管理员鉴权及在线目标 Computer。选择能够覆盖报错时间的最近时间范围：当前协议支持 1 小时、3 小时、1 天、3 天或 14 天，截止时间为任务创建时刻；不能自行指定历史起止时间。日志实际留存可能短于请求范围。
2. 创建任务并保存返回的 taskId。服务端持久化任务，以 `computer.runtime-log-recall` 通知目标 desktopd；desktopd 通过 HTTP 获取并校验任务，随后收集、打包和上传日志。
3. 查询到可下载状态后继续。等待设备和设备处理中都表示未完成；失败时记录 failureCode / failureMessage。按工具返回和任务 deadline 有界等待，单次等待不超过 60 秒。当前任务期限为 25 分钟，Computer 离线、连接变更或超时会阻止完成。
4. 为成功任务生成下载链接，下载到会话临时目录，校验任务中返回的包 SHA256 后在独立目录安全解包，读取 `manifest.json` 和相关日志。下载链接当前有效期为 10 分钟；过期后为仍在下载保留期内的任务重新生成链接，不直接新建重复任务。下载保留期当前为完成后的 14 天。
5. 对齐请求时间与实际覆盖时间、版本、日志清单、未知时间戳行及 `truncated`。当前召回包包含可获取的 `companion.log`、`desktopd.log`、`runtime-host.log` 和临时目录中的 `tutti-codex-appserver-startup.jsonl`，按时间过滤并合并可识别的轮转文件。清单中的内容校验值与任务返回的整个压缩包校验值按各自作用域使用。部分文件为空或包被截断时，说明受影响的判断。

完成条件：日志包已下载、校验、读取并保存证据，或已记录准确的失败/覆盖缺口与恢复条件。创建任务、得到链接或配置 MCP 名称都不表示已经拿到日志。服务地址、工具或权限缺失交给接入维护人；QA 仅补充无法从现有证据取得的现场信息。

## 日志里的 request id

包含 tutti #2736 的 Computer 版本在 `desktopd.log` 里为请求写两类日志，旧版本没有，读不到时照常按时间与状态事件核对：

| 事件 | 方向 | 关联字段 |
|---|---|---|
| `desktop.local_api.request` | Web → desktopd 本地接口 | `correlation_id`：Web 发来的 `X-Tutti-Request-ID`，与 Web 日志中该请求的 `requestId` 相同 |
| `desktop.outbound_network.api_request` | desktopd → tutti-server | `request_id`：网关分配的 `x-zk-request-id`，在 tutti-server 日志中可查；`correlation_id`：触发它的 Web 请求 |

两者都记录 method、path（不含 query）、`status_code`、`duration_ms`。同一请求处理过程中其他带 context 的日志也带同一个 `correlation_id`。`desktop.agentexecutor.control_plane_http` 中 `request_id` 同样是网关 id，`client_request_id` 是 desktopd 自己生成、会被网关替换的 id，查不到服务端日志。

故障时间附近失败的 `desktop.outbound_network.api_request`，把它的 method、路径、状态码和 `request_id` 写进排查线索；打回时不查服务端日志，RD 排查时按 id 去查。
