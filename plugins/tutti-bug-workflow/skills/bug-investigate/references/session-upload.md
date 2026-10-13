# 提 Bug 结束后的会话上传

本页是 `bug-investigate` 的收尾步骤：登记与现场采集全部完成后，把当前会话上传到 Tutti 管理端 Session 日志服务，供后续优化。会话日志与 Web、Computer、Server 现场日志用途不同，不发布到 Room。

tutti-ops 的会话上传能力与权限由 bug-setup 准备；上传前用 `tutti-ops diagnostics +upload-session-log --help` 确认命令存在，缺失时记为维护侧阻塞。

## 触发条件

整条 Bug 的登记与现场采集全部完成后上传一次：记录已建、字段已写、三类现场都有了结果（包括等待中的 Computer 召回已结束），只剩需要用户补充的项也算完成。仍在采集或等待召回时不上传；用户明确结束本次登记时也上传。

**无状态去重**：tutti-ops 不提供查询已上传会话的命令，也不按内容去重，所以「本会话是否已上传、uploadId 是什么」只记在会话上下文中，同一会话只上传一次。上传失败不影响已完成的登记，最终回复如实说明。本任务授权已包含这一收尾操作，无需另向用户确认；用户明确要求不上传时遵循。

## 2. 绑定当前 provider 与本会话

provider 表示产生会话记录的 Agent 宿主，例如 Codex 或 Claude Code，不是模型名称、API 厂商或本条 Bug 的 Computer Agent。优先使用宿主明确提供的当前 provider、会话 ID 与原生日志路径；再用原生日志元数据交叉核对，记录来源。

| 当前宿主 | provider 与本会话定位 |
|---|---|
| Codex | `provider=codex`；使用宿主当前 thread/session ID。运行时实际提供 `CODEX_THREAD_ID`／`CODEX_SESSION_ID` 时可交叉核对；在实际 Codex 数据根的 `sessions/` 中按该 ID 找 `.jsonl`，读取 `session_meta.payload.id` 核实。数据根以实际宿主配置为准，常见为 `CODEX_HOME` 或 `~/.codex` |
| Claude Code | `provider=claude`；使用宿主提供的当前 session ID、transcript 路径或可信 hook 元数据，在实际配置根的对应项目会话目录核对 JSONL 中的 `sessionId`；常见根为 `CLAUDE_CONFIG_DIR` 或 `~/.claude`。环境变量仅在确实由当前宿主提供时作为依据 |
| 其他宿主 | 使用该宿主实际 provider 标识与当前 session 导出/日志入口，核对 ID 和上下文来源；CLI 将标识转小写，允许字母、数字、下划线和连字符，最长 64 字符。原生不是 JSONL 时，用该宿主有据可查的 JSONL 导出方式，记录格式转换 |

只定位本会话，保留用户输入、分析、工具调用及结果、方案与验证等实际可导出的完整上下文。会话中包含多个 Bug 时只上传一次，在各条 Bug 的最终回复里说明。子代理会话另属自己的 session，主会话中的协作记录随主会话保留；仅在明确需要且已授权时另传子会话。

当前 ID、provider 或日志入口无法确认时保存 `blocked` 与具体缺口，继续已授权的独立工作；使用当前宿主可用的导出/定位接口恢复。仅凭日志最新修改时间、已安装哪家 CLI 或模型名称不能选择会话；人工整理的分析摘要也不能代替原生上下文。

## 3. 生成快照

1. 确认 Task 已建好（或已按 SKILL 第 5 步问完、用户明确结束），再读取当前会话日志，复制到会话临时目录，例如 `$TMP/session-task-<operation_id>-<session_id>.jsonl`，文件名便于管理端按 Task 追溯。保留 provider 原生 JSONL 结构，文件权限 0600。
2. CLI 只复制文件并上传，不解析 JSONL、不自动脱敏，也不会自动寻找当前 session。发现实际凭证时对快照脱敏，原会话不改写。快照只包含当时已落盘的记录，不包含之后的最终回复。
3. 只上传这一份快照；当前 CLI 请求只接受 provider 和文件，Task 与会话的对应关系体现在文件名里，不虚构关联字段。

## 4. 上传并核对结果

将环境、provider 和文件替换为上一节核实的值。先预览同一操作，再直接执行：

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics +upload-session-log --provider PROVIDER --file SNAPSHOT.jsonl --dry-run
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics +upload-session-log --provider PROVIDER --file SNAPSHOT.jsonl --yes
```

dry-run 零网络，不读取文件或验证权限。实际工作流为私有文件副本 → 创建上传记录 → 签名 PUT → complete 确认。仅在退出码成功、`ok=true`、`meta.complete=true`，且 `data.upload` 中 uploadId、provider、fileName、sizeBytes 匹配快照、`status=uploaded` 时记录上传成功。只有创建记录或 PUT 成功不算完成。签名 URL、管理 Token/Cookie 不进入回执或 Task；对象传输由 CLI 隔离认证。

把 uploadId 与结果记在会话上下文中；`uploaded`、`partial`、`unknown`、`blocked` 分别如实说明。

## 5. 部分上传与恢复

- 已返回 uploadId，但 PUT 或确认失败：保存 `partial`、真实失败步骤与回执。先对该 uploadId 执行下方 complete，再核对返回记录。当前独立 complete 的 `meta.complete` 可以为 null；以 `ok=true` 及匹配的 `data.upload.status=uploaded` 判断恢复成功。
- complete 表明对象尚未上传、缺失或大小不符：先区分上传未完成和确认暂时失败；确认旧对象无法恢复后，才用同一稳定快照重新上传并记录新旧 uploadId 的关系。当前接口没有重签或断点续传能力。
- 首次申请响应丢失且没有 uploadId：记 `unknown`，通过管理端实际 Session 日志查询入口核对 provider、文件名、字节数和时间，或保存维护侧核对条件。未核实结果前不自动重跑创建链。
- 认证、权限、服务、文件大小或会话定位受阻：保存错误码和具体恢复条件，按已有 Setup 规则处理可自行恢复的项；真实缺口面向维护方，不要求 QA 提供 Agent 宿主会话文件。文件上限按服务端实际配置核对，保留完整快照，不静默截成分析摘要。

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics session-logs complete --upload-id UPLOAD_ID --yes
```

完成条件：上传已确认（`status=uploaded`），或已如实说明受阻/部分/未知结果与恢复动作。最终反馈简要说明 session 上传结果；上传成功可给出 uploadId，受阻说明影响及下一步，业务处理结果分别报告。
