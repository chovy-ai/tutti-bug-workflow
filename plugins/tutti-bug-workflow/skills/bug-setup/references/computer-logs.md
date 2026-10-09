# 本机 Computer 日志路径

Setup 配置 `computer-local.paths`；采集由 bug-investigate 的脚本执行。

## 本地：读取指定文件

`computer-local.paths` 保存用户或项目维护人指定的文件路径，可配置一个或多个文件。支持绝对路径、`~/`（执行用户的主目录）、`${TMPDIR}/` 和 `${TEMP}/`（明确指定的临时目录环境变量）。配置与介绍不写入个人用户名或机器专属临时目录。读取前使用 `scripts/workbench.py` 的 `resolve_log_path` 将配置项解析为执行机器上的绝对路径；变量缺失或其值不是绝对目录时记录配置缺口，不替换为猜测目录。只读这些明确指定的文件，按问题时间和定位标识筛选，保留堆栈等相邻上下文；需要轮转日志或其他组件文件时取得相应明确路径后补充配置。以下是默认 state root 的本机场景写法：

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
