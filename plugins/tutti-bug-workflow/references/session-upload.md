# 每轮 Bug 处理后的会话上传

`investigate`、`solution`、`execute` 每轮保存报告、回填与状态后，最终反馈前执行本页。分析完成、等待 QA/RD、验收、验证失败和阻塞都需要保留本轮会话，便于后续优化；恢复后形成新一轮快照。纯 Setup 不触发 Bug 会话上传。用户明确限制上传时记录范围并遵循其要求。

会话 JSONL 上传到已配置的 Tutti 管理端 Session 日志服务，属于工作流的收尾操作；它与 Web、Computer、Server 现场日志用途不同，不追加为飞书日志附件。上传失败保存独立的归档状态，不把已完成的业务工作改成失败，也不声称归档完成。

## 1. 核对 CLI、目标与权限

先复用实际 tutti-ops 入口与 [管理端认证](tutti-ops-computer-logs.md#环境与认证)。2026-10-08 已核对发布包 `@tutti-os/tutti-ops-cli@0.1.7` 的 `dist/sessionLogs.js`、`dist/workflows/sessionLogs.js` 和操作注册表；0.1.6 没有此能力。以后以实际能力为准：

```sh
tutti-ops diagnostics +upload-session-log --help
tutti-ops schema diagnostics.+upload-session-log
tutti-ops schema diagnostics.session-logs.complete
```

命令缺失时按已授权的工具准备流程升级官方包 `npm install -g @tutti-os/tutti-ops-cli`，保留配置与认证，再检查帮助/schema；现有 Setup 的“命令可执行”不能代替 session 能力检查。自定义 CLI 先核对实际入口，不擅自覆盖。安装或升级后立即核对身份与所需权限。

使用已有配置中的真实管理端环境；默认管理入口 `https://admin.tutti.sh` 由 CLI 归一化为 API origin。需要有效的认证、管理密钥 diagnostics write 范围及管理员 `session_logs.write` 权限，存储服务也须已部署。只读身份/权限检查和 dry-run 不证明实际上传可用。`--mode write --yes` 执行已授权的收尾操作，不另索要重复确认；它们不提升服务端权限。凭证复用 CLI 原生存储，不写进命令、JSONL 元信息或报告。

## 2. 绑定当前 provider 与本会话

provider 表示产生会话记录的 Agent 宿主，例如 Codex 或 Claude Code，不是模型名称、API 厂商或本条 Bug 的 Computer Agent。优先使用宿主明确提供的当前 provider、会话 ID 与原生日志路径；再用原生日志元数据交叉核对，记录来源。

| 当前宿主 | provider 与本会话定位 |
|---|---|
| Codex | `provider=codex`；使用宿主当前 thread/session ID。运行时实际提供 `CODEX_THREAD_ID`／`CODEX_SESSION_ID` 时可交叉核对；在实际 Codex 数据根的 `sessions/` 中按该 ID 找 `.jsonl`，读取 `session_meta.payload.id` 核实。数据根以实际宿主配置为准，常见为 `CODEX_HOME` 或 `~/.codex` |
| Claude Code | `provider=claude`；使用宿主提供的当前 session ID、transcript 路径或可信 hook 元数据，在实际配置根的对应项目会话目录核对 JSONL 中的 `sessionId`；常见根为 `CLAUDE_CONFIG_DIR` 或 `~/.claude`。环境变量仅在确实由当前宿主提供时作为依据 |
| 其他宿主 | 使用该宿主实际 provider 标识与当前 session 导出/日志入口，核对 ID 和上下文来源；CLI 将标识转小写，允许字母、数字、下划线和连字符，最长 64 字符。原生不是 JSONL 时，用该宿主有据可查的 JSONL 导出方式，记录格式转换 |

只定位本会话，保留用户输入、分析、工具调用及结果、方案与验证等实际可导出的完整上下文。会话中包含多个 Bug 时，同一快照可由相关 Bug 档案引用。子代理会话另属自己的 session，主会话中的协作记录随主会话保留；仅在明确需要且已授权时另传子会话。

当前 ID、provider 或日志入口无法确认时保存 `blocked` 与具体缺口，继续已授权的独立工作；使用当前宿主可用的导出/定位接口恢复。仅凭日志最新修改时间、已安装哪家 CLI 或模型名称不能选择会话；人工整理的分析摘要也不能代替原生上下文。

## 3. 固定本轮快照

1. 完成本轮业务报告、字段回填、状态与剩余问题的保存，再读取当前会话日志。把快照复制到本轮本地证据目录，可用 `BUG_ID-SCENE-RUN_ID-SESSION_ID.jsonl` 命名便于管理端追溯；保留 provider 原生 JSONL 结构，限制文件访问权限（POSIX 目录 0700、文件 0600）。记录 session ID、来源路径、快照时刻、实际覆盖、字节数和 SHA-256。
2. CLI 只复制文件并上传，不解析 JSONL、不自动脱敏，也不会自动寻找当前 session。沿用凭证处理规则；发现实际凭证时对快照脱敏，记录范围并保留必要上下文，原会话不改写。快照包含当时已落盘的记录；源文件仍在写入、末行不完整或宿主未导出部分上下文时注明限制，不能声称包含上传之后的最终回复。
3. 在 `bugs/BUG_ID/session-uploads.jsonl` 查已有回执。相同 provider、session ID 与快照 SHA-256 已成功上传时复用 uploadId；同一轮重试复用稳定快照与回执。后续 Bug 处理新增上下文时上传新快照；上传本身与最终反馈不触发递归补传。CLI 服务端不按内容去重。

只上传这一份快照；本地回执、清单、Bug 元信息、整个日志目录与压缩包不随其上传。session ID、Bug ID、场景与运行 ID 在本地建立对应关系，当前 CLI 请求仅接受 provider 和文件，不虚构关联字段。

## 4. 上传并核对结果

将环境、provider 和文件替换为上一节核实的值。先预览同一操作，再直接执行：

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics +upload-session-log --provider PROVIDER --file SNAPSHOT.jsonl --dry-run
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics +upload-session-log --provider PROVIDER --file SNAPSHOT.jsonl --yes
```

dry-run 零网络，不读取文件或验证权限。实际工作流为私有文件副本 → 创建上传记录 → 签名 PUT → complete 确认。仅在退出码成功、`ok=true`、`meta.complete=true`，且 `data.upload` 中 uploadId、provider、fileName、sizeBytes 匹配快照、`status=uploaded` 时记录上传成功。只有创建记录或 PUT 成功不算完成。签名 URL、管理 Token/Cookie 不进入回执或飞书；对象传输由 CLI 隔离认证。

每次尝试向本地 `session-uploads.jsonl` 追加一条结果：Bug/场景/运行 ID、provider 及判断依据、session ID/原路径、快照路径/时刻/覆盖/SHA-256/字节数/脱敏范围、实际 CLI 版本/API origin、uploadId、步骤、状态及恢复动作。`uploaded`、`partial`、`unknown`、`blocked`、用户限制的 `skipped` 分别记录，不增加业务根因确认程度或改变批准版本。

## 5. 部分上传与恢复

- 已返回 uploadId，但 PUT 或确认失败：保存 `partial`、真实失败步骤与回执。先对该 uploadId 执行下方 complete，再核对返回记录。当前独立 complete 的 `meta.complete` 可以为 null；以 `ok=true` 及匹配的 `data.upload.status=uploaded` 判断恢复成功。
- complete 表明对象尚未上传、缺失或大小不符：先区分上传未完成和确认暂时失败；确认旧对象无法恢复后，才用同一稳定快照重新上传并记录新旧 uploadId 的关系。当前接口没有重签或断点续传能力。
- 首次申请响应丢失且没有 uploadId：记 `unknown`，通过管理端实际 Session 日志查询入口核对 provider、文件名、字节数和时间，或保存维护侧核对条件。未核实结果前不自动重跑创建链。
- 认证、权限、服务、文件大小或会话定位受阻：保存错误码和具体恢复条件，按已有 Setup 规则处理可自行恢复的项；真实缺口面向维护方，不要求 QA 提供 Agent 宿主会话文件。文件上限按服务端实际配置核对，保留完整快照，不静默截成分析摘要。

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics session-logs complete --upload-id UPLOAD_ID --yes
```

完成条件：本轮上传已确认且关联回执已保存，或已记录真实的受阻/部分/未知结果与恢复动作。最终反馈简要说明 session 上传结果；上传成功可给出 uploadId，受阻说明影响及下一步，业务处理结果分别报告。
