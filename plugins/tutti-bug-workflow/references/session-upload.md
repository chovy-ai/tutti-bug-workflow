# 提 Bug 确认结束后的会话上传

本页是 `bug-investigate` 的提 Bug 收尾节点。先根据用户已授权范围确认本次提 Bug 已结束，再于最终反馈前上传当前 provider 的本会话上下文，供后续优化。一次回复结束、保存进度或收到补充材料不等于提 Bug 结束。方案协商、修复验证、纯 Setup 和 Skill 维护不自动触发本节点；用户明确限制上传时记录范围并遵循其要求。

会话 JSONL 上传到已配置的 Tutti 管理端 Session 日志服务，属于工作流的收尾操作；它与 Web、Computer、Server 现场日志用途不同，不追加为飞书日志附件。上传失败保存独立的归档状态，不把已完成的业务工作改成失败，也不声称归档完成。

## 触发条件：先确认提 Bug 结束

| 当前情况 | 收尾节点 |
|---|---|
| 默认完整分析已确认根因，报告和必要证据已保存，字段回填并回读成功，已进入 `pending_solution` | 本次提 Bug 已完成，执行上传；后续 RD 方案和修复属于交接后的流程 |
| 用户明确只登记或只补附件，授权范围内的登记、证据保存和回填均成功 | 本次限定范围已完成，执行上传；不宣称根因已确认 |
| 用户明确结束本次提 Bug 范围 | 保存指令来源、未完成项及真实业务状态后执行上传 |
| 仍在分析/采集、等待 QA 补充、必要验证暂时受阻或回填失败 | 保持待执行，保存进度与恢复条件；不因本轮回复结束上传 |
| 已执行同一结束节点，只有上传重试、最终反馈、状态查询或其他流程新增消息 | 复用快照和回执或恢复失败步骤；不生成新上传 |

在本地 `session-uploads.jsonl` 保存本次结束依据、结束时刻、输入版本与结束运行 ID，标识该节点。这个标识由业务结束事件决定，不能每次重试重新生成。已有任务授权足以执行收尾，无需另向用户确认。流程恢复后须重新满足结束条件才进入本节点；已完成的提 Bug 被新输入重新打开后，在新的提 Bug 范围确认结束时才形成新节点。上传权限或服务失败只留下归档待恢复项，不把提 Bug 改回处理中。

## 1. 核对 CLI、目标与权限

先复用实际 tutti-ops 入口与 [管理端认证](tutti-ops-computer-logs.md#环境与认证)。2026-10-08 已核对发布包 `@tutti-os/tutti-ops-cli@0.1.7` 的 `dist/sessionLogs.js`、`dist/workflows/sessionLogs.js` 和操作注册表；0.1.6 没有此能力。以后以实际能力为准：

```sh
tutti-ops diagnostics +upload-session-log --help
tutti-ops schema diagnostics.+upload-session-log
tutti-ops schema diagnostics.session-logs.complete
```

命令缺失时按已授权的工具准备流程升级官方包 `npm install -g @tutti-os/tutti-ops-cli`，保留配置与认证，再检查帮助/schema；现有 Setup 的“命令可执行”不能代替 session 能力检查。自定义 CLI 先核对实际入口，不擅自覆盖。安装或升级后立即核对身份与所需权限。

使用已有配置中的真实管理端环境；默认管理入口 `https://admin.tutti.sh` 由 CLI 归一化为 API origin。需要有效的认证、管理密钥总权限与 diagnostics 模块 write 范围及管理员 `session_logs.write` 权限，存储服务也须已部署。先用只读 `auth status --metadata-only true` 核对返回的 `token.access_mode` 与 `token.module_grants`，再用 `auth permissions` 核对管理员权限；分别记录非秘密结果。`access_mode=read` 时明确记录密钥只读的阻塞，通过已有隐藏输入流程配置有相应写权限的密钥再复查，管理员具有 `session_logs.write` 不能抵消只读密钥限制。模块授权按实际契约核对，不从字段为空推断上传权限。

只读身份/权限检查和 dry-run 不证明实际上传可用。`--mode write --yes` 执行已授权的收尾操作，不另索要重复确认；它们不提升服务端权限。凭证复用 CLI 原生存储，不写进命令、JSONL 元信息或报告。

## 2. 绑定当前 provider 与本会话

provider 表示产生会话记录的 Agent 宿主，例如 Codex 或 Claude Code，不是模型名称、API 厂商或本条 Bug 的 Computer Agent。优先使用宿主明确提供的当前 provider、会话 ID 与原生日志路径；再用原生日志元数据交叉核对，记录来源。

| 当前宿主 | provider 与本会话定位 |
|---|---|
| Codex | `provider=codex`；使用宿主当前 thread/session ID。运行时实际提供 `CODEX_THREAD_ID`／`CODEX_SESSION_ID` 时可交叉核对；在实际 Codex 数据根的 `sessions/` 中按该 ID 找 `.jsonl`，读取 `session_meta.payload.id` 核实。数据根以实际宿主配置为准，常见为 `CODEX_HOME` 或 `~/.codex` |
| Claude Code | `provider=claude`；使用宿主提供的当前 session ID、transcript 路径或可信 hook 元数据，在实际配置根的对应项目会话目录核对 JSONL 中的 `sessionId`；常见根为 `CLAUDE_CONFIG_DIR` 或 `~/.claude`。环境变量仅在确实由当前宿主提供时作为依据 |
| 其他宿主 | 使用该宿主实际 provider 标识与当前 session 导出/日志入口，核对 ID 和上下文来源；CLI 将标识转小写，允许字母、数字、下划线和连字符，最长 64 字符。原生不是 JSONL 时，用该宿主有据可查的 JSONL 导出方式，记录格式转换 |

只定位本会话，保留用户输入、分析、工具调用及结果、方案与验证等实际可导出的完整上下文。会话中包含多个 Bug 时，同一快照可由相关 Bug 档案引用。子代理会话另属自己的 session，主会话中的协作记录随主会话保留；仅在明确需要且已授权时另传子会话。

当前 ID、provider 或日志入口无法确认时保存 `blocked` 与具体缺口，继续已授权的独立工作；使用当前宿主可用的导出/定位接口恢复。仅凭日志最新修改时间、已安装哪家 CLI 或模型名称不能选择会话；人工整理的分析摘要也不能代替原生上下文。

## 3. 固定结束节点的快照

1. 先在 `bugs/BUG_ID/session-uploads.jsonl` 查该结束节点的已有快照和回执。已成功上传时复用 uploadId；重试时复用稳定快照，按第 5 节恢复，不因源会话继续增长重新复制或创建上传。同一快照的 provider、session ID 与 SHA-256 已有成功回执时也可复用，记录本节点的关联。CLI 服务端不按内容去重。
2. 没有已有快照时，确认业务报告、字段回填、状态与剩余问题已保存，再读取当前会话日志，将快照复制到本次结束节点的本地证据目录。可用 `BUG_ID-investigate-CLOSURE_RUN_ID-SESSION_ID.jsonl` 命名便于管理端追溯；保留 provider 原生 JSONL 结构，限制文件访问权限（POSIX 目录 0700、文件 0600）。仅在新的提 Bug 范围再次确认结束时生成新快照；上传本身与最终反馈不触发递归补传。
3. CLI 只复制文件并上传，不解析 JSONL、不自动脱敏，也不会自动寻找当前 session。沿用凭证处理规则；发现实际凭证时对快照脱敏，记录范围并保留必要上下文，原会话不改写。记录 session ID、来源路径、快照时刻、实际覆盖、脱敏后的字节数和 SHA-256。快照包含当时已落盘的记录；源文件仍在写入、末行不完整或宿主未导出部分上下文时注明限制，不能声称包含上传之后的最终回复。

只上传这一份快照；本地回执、清单、Bug 元信息、整个日志目录与压缩包不随其上传。session ID、Bug ID、场景与运行 ID 在本地建立对应关系，当前 CLI 请求仅接受 provider 和文件，不虚构关联字段。

## 4. 上传并核对结果

将环境、provider 和文件替换为上一节核实的值。先预览同一操作，再直接执行：

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics +upload-session-log --provider PROVIDER --file SNAPSHOT.jsonl --dry-run
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics +upload-session-log --provider PROVIDER --file SNAPSHOT.jsonl --yes
```

dry-run 零网络，不读取文件或验证权限。实际工作流为私有文件副本 → 创建上传记录 → 签名 PUT → complete 确认。仅在退出码成功、`ok=true`、`meta.complete=true`，且 `data.upload` 中 uploadId、provider、fileName、sizeBytes 匹配快照、`status=uploaded` 时记录上传成功。只有创建记录或 PUT 成功不算完成。签名 URL、管理 Token/Cookie 不进入回执或飞书；对象传输由 CLI 隔离认证。

每次尝试向本地 `session-uploads.jsonl` 追加一条结果：Bug/场景/结束运行 ID、结束依据/时刻/输入版本、provider 及判断依据、session ID/原路径、快照路径/时刻/覆盖/SHA-256/字节数/脱敏范围、实际 CLI 版本/API origin、uploadId、步骤、状态及恢复动作。`uploaded`、`partial`、`unknown`、`blocked`、用户限制的 `skipped` 分别记录，不增加业务根因确认程度或改变批准版本。提 Bug 尚未结束时不记为上传 `skipped`，节点仍待执行。

## 5. 部分上传与恢复

- 已返回 uploadId，但 PUT 或确认失败：保存 `partial`、真实失败步骤与回执。先对该 uploadId 执行下方 complete，再核对返回记录。当前独立 complete 的 `meta.complete` 可以为 null；以 `ok=true` 及匹配的 `data.upload.status=uploaded` 判断恢复成功。
- complete 表明对象尚未上传、缺失或大小不符：先区分上传未完成和确认暂时失败；确认旧对象无法恢复后，才用同一稳定快照重新上传并记录新旧 uploadId 的关系。当前接口没有重签或断点续传能力。
- 首次申请响应丢失且没有 uploadId：记 `unknown`，通过管理端实际 Session 日志查询入口核对 provider、文件名、字节数和时间，或保存维护侧核对条件。未核实结果前不自动重跑创建链。
- 认证、权限、服务、文件大小或会话定位受阻：保存错误码和具体恢复条件，按已有 Setup 规则处理可自行恢复的项；真实缺口面向维护方，不要求 QA 提供 Agent 宿主会话文件。文件上限按服务端实际配置核对，保留完整快照，不静默截成分析摘要。

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode write diagnostics session-logs complete --upload-id UPLOAD_ID --yes
```

完成条件：该结束节点的上传已确认且关联回执已保存，或已记录真实的受阻/部分/未知结果与恢复动作。最终反馈简要说明 session 上传结果；上传成功可给出 uploadId，受阻说明影响及下一步，业务处理结果分别报告。
