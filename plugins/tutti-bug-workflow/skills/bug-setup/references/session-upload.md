# 会话上传的接入准备

bug-investigate 在排查结束后上传会话；Setup 负责确认 tutti-ops 具备该能力与权限。

## 1. 核对 CLI、目标与权限

先复用实际 tutti-ops 入口与 [管理端认证](tutti-ops-computer-logs.md#环境与认证)。2026-10-13 已核对发布包 `@tutti-os/tutti-ops-cli@0.1.8`：上传与 complete 自 0.1.7 起提供，0.1.8 新增只读 `session-logs list` 与 `+download-session-log`；0.1.6 没有此能力。以后以实际能力为准：

```sh
tutti-ops diagnostics +upload-session-log --help
tutti-ops schema diagnostics.+upload-session-log
tutti-ops schema diagnostics.session-logs.complete
tutti-ops schema diagnostics.session-logs.list
```

命令缺失时按已授权的工具准备流程升级官方包 `npm install -g @tutti-os/tutti-ops-cli`，保留配置与认证，再检查帮助/schema；现有 Setup 的“命令可执行”不能代替 session 能力检查。自定义 CLI 先核对实际入口，不擅自覆盖。安装或升级后立即核对身份与所需权限。

使用已有配置中的真实管理端环境；默认管理入口 `https://admin.tutti.sh` 由 CLI 归一化为 API origin。需要有效的认证、管理密钥总权限与 diagnostics 模块 write 范围，且当前账号是管理员，存储服务也须已部署。tsh-admin-server 已让所有已登录管理员默认具备 `session_logs.upload`（上传与 complete），无需再按 UID 授予 `session_logs.write`；CLI schema 中仍显示的 `session_logs.write` 只是声明，不在本地校验。查询与下载另需 `session_logs.read`（或已有的 `session_logs.write`），上传权限不包含它；它只用于结果未知时的核对，缺少时不阻塞上传。先用只读 `auth status --metadata-only true` 核对返回的 `token.access_mode` 与 `token.module_grants`，再用 `auth permissions` 核对管理员身份及是否具备 `session_logs.read`；分别记录非秘密结果。`access_mode=read` 时明确记录密钥只读的阻塞，通过已有隐藏输入流程配置有相应写权限的密钥再复查，管理员上传权限不能抵消只读密钥限制。模块授权按实际契约核对，不从字段为空推断上传权限。

只读身份/权限检查和 dry-run 不证明实际上传可用。`--mode write --yes` 执行已授权的收尾操作，不另索要重复确认；它们不提升服务端权限。凭证复用 CLI 原生存储，不写进命令、JSONL 元信息或报告。
