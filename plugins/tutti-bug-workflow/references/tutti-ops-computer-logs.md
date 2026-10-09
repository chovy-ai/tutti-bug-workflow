# 用 tutti-ops 获取远端 Computer 日志

提 Bug 时由 `scripts/collect_computer.py` 自动执行本页的定位已有任务、创建、等待、生成链接、下载与校验；本页供脚本失败排查或手动操作时参考。这是 [Computer 日志获取](computer-logs.md) 中远端日志召回协议的 CLI 入口；本机继续读取已确认的文件。2026-09-30 核对了本机实际安装的 npm 包 `@tutti-os/tutti-ops-cli@0.1.6` 的 Computer 帮助、能力清单、六个操作的 schema，以及零网络创建与下载链接预览。

## 准备与发现

setup 运行 `scripts/workbench.py setup-tutti-ops --install`。已有可用命令时复用；缺少时检查 Node.js >=20、npm，并按用户指定方式安装：

```sh
npm install -g @tutti-os/tutti-ops-cli
```

辅助脚本记录实际可执行路径和包版本；全局安装目录未在 PATH 中时使用返回路径。此 npm 包没有根级 `--version` 参数，版本从对应包的 `package.json` 读取；没有版本元数据时记录 unknown，再按帮助与 schema 核对能力。此安装脚本不启动登录、不查询远端账号或日志；Agent 在全体安装阶段结束后立即进入下文的认证检查与处理。

使用具体 Bug 前发现实际命令，以下示例的 `tutti-ops` 可替换为 setup 返回的入口：

```sh
tutti-ops computer --help
tutti-ops capabilities --module computer
tutti-ops schema computer.devices.list
tutti-ops schema computer.devices.get
tutti-ops schema computer.log-recalls.list
tutti-ops schema computer.log-recalls.get
tutti-ops schema computer.log-recalls.create
tutti-ops schema computer.log-recalls.download-url
```

当前 npm 包提供上面的原子操作，不提供 `computer +collect-logs` 或 `computer +download-logs`。此前核对的 Git main `5c7111ca224e07d29fcfaa2a48ef589d0515fb35`（源码版本同为 0.1.6）包含组合工作流，但不能据此调用已安装包中不存在的命令。未来入口的能力清单实际包含组合命令时，再读取其 schema 使用；组合下载仍需核对是否只生成链接。

## 环境与认证

管理端入口为 [https://admin.tutti.sh](https://admin.tutti.sh)，用户已确认；已安装的 tutti-ops 0.1.7 会将这个管理端地址归一化为 API origin `https://tutti.sh`，按本机 `dist/config.js` 和实际帮助核对。显式传入 `--admin-url`，复用与该 origin 匹配的 Token。其他环境使用其已确认地址和认证；CLI 请求路径已包含 `/api/desktop`，origin 保留根地址。

tutti-ops 远端访问需要从 [管理端](https://admin.tutti.sh) 取得 Token。由环境维护方准备，普通 QA 反馈按 [QA 反馈规则](qa-dialogue.md) 提出必要的现场问题。已有匹配 origin 且有效的 Token 时复用；本机调用成功说明已有 Token 可用，仍需为新使用者准备各自的认证与权限。

需要维护方获取 Token、登录或补充日志权限时，先按 [面向使用者的管理端教程](setup-user-guide.md#远端日志如何授权) 引导本人完成；下面保留执行侧认证与验证步骤。

认证准备按以下顺序进行；以下示例使用已确认的 `https://admin.tutti.sh`，切换环境时替换为对应地址：

1. **取得 Token**：环境维护方登录 [管理端](https://admin.tutti.sh)，获取具备本轮所需权限的 Token。缺少管理端账号或 Token 签发权限时记录维护侧缺口；Token 缺失或失效时由该入口补齐。具体页面和有效期按管理端实际说明核对。
2. **直接配置 Token**：安装阶段结束后运行 `python3 PLUGIN_SOURCE/scripts/workbench.py configure-tutti-token --admin-url https://admin.tutti.sh`，在本机终端隐藏输入 Token。无需另行运行 `tutti-ops auth login`。该入口仅向校验子进程注入 `TUTTI_ADMIN_TOKEN`，移除该子进程的 `TUTTI_ADMIN_COOKIE`，通过 CLI 的只读 `auth status --metadata-only true` 验证后，原子保存到 CLI 原生的 `~/.config/tutti-ops/config.json`（POSIX 文件权限 0600），后续 tutti-ops 命令自动复用。失败保留旧配置，不回显上游原始输出。`--token-env` 可读取并保存已由宿主安全注入的 `TUTTI_ADMIN_TOKEN`，`--token-stdin` 可从安全输入通道读取；Token 不放在命令参数、聊天、插件源码或工作台报告中。已有有效且 origin 匹配的 Token 直接复用，更换环境时重新核对。
3. **验证能力**：在已授权认证检查时，运行 `tutti-ops --admin-url https://admin.tutti.sh --mode read auth status --metadata-only true` 和 `auth permissions`，仅保留非秘密身份/权限元数据，再实际查询已确认 Computer 及其日志任务。身份有效、目录可读、历史包下载和新召回各自有独立状态。Token 已导入本身不表示全部业务权限已通过。

独立安装步骤只准备 CLI；完整 Setup 或选中远端能力时，Agent 接着按 [主动补齐授权](setup-user-guide.md#主动补齐授权) 检查实际 origin 的身份和权限。缺少 Token 时立即提供管理密钥入口并准备 `configure-tutti-token` 的隐藏输入终端；本人配置后复查身份、权限和设备目录，安装完成与远端可用分别报告。

目录查询、任务查询与生成历史包链接是 read；创建召回是 write。CLI 的 `--mode` 是本地执行策略，不授予服务端权限。缺少身份、权限或路由时分别记录缺口，不能仅凭 401 判定 Token 是唯一原因。

## 定位目标与已有任务

先按 [Computer 定位与 QA 询问](computer-target.md) 取得明确目标。下列名称、Computer ID 和任务 ID 均需替换为已确认的真实值，API origin 按实际环境替换：

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode read computer devices list --name-query "COMPUTER_NAME" --page-all --page-limit 10
tutti-ops --admin-url https://admin.tutti.sh --mode read computer devices get --computer-id "COMPUTER_ID"
tutti-ops --admin-url https://admin.tutti.sh --mode read computer log-recalls list --computer-id "COMPUTER_ID" --page-all --page-limit 10
```

实际 npm schema 支持 `nameQuery`、`connectionStatus`、`platform`、`hostArtifactVersion`、`pageSize` 和 `pageToken`，没有 `--owner-query`。从真实返回的 owner、名称、平台和版本核对 QA 与目标，存在多个候选时请 QA 选择；不要默认选择第一台或只查询在线设备。

单页结果按 `data.computers` 或 `data.tasks` 读取；`--page-all` 成功结果为 `data.items`。检查退出码、`ok`、`meta.complete` 与返回游标，达到分页上限不表示已查完。现有可下载任务的 Computer、环境、故障时间覆盖和保留期匹配时，优先复用；未知覆盖记录为待核对，下载后仍需检查清单。

## 没有可复用任务时采集

原子操作由 Agent 串联：查询历史 → 核对覆盖 → 必要时创建 → 保存 taskId → 查询状态 → 生成链接。用户已授权本次目标与范围的日志采集时，先做零网络预览，再执行同一操作，不重复索要确认：

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode write computer log-recalls create --computer-id "COMPUTER_ID" --range-preset 2 --dry-run
tutti-ops --admin-url https://admin.tutti.sh --mode write computer log-recalls create --computer-id "COMPUTER_ID" --range-preset 2 --yes
```

`rangePreset` 的协议整数为：1=1 小时、2=3 小时、3=1 天、4=3 天、5=14 天。故障时间保存为带时区的 ISO-8601；新召回按创建时刻向前取范围，不能指定任意历史起止时间。原子命令没有 `--incident-at`、`--range` 或 `--wait`，故障时间用于 Agent 自己判断覆盖。

创建返回的 `data` 是服务端任务对象；按真实字段立即保存 taskId，再查询：

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode read computer log-recalls get --computer-id "COMPUTER_ID" --task-id "TASK_ID"
```

按实际响应解析状态：协议 1=等待设备、2=设备处理中、3=可下载、4=失败；服务端也可能返回对应枚举字符串。失败记录 failureCode／failureMessage，等待受任务 deadline 约束，单次等待不超过 60 秒。创建返回不明或网络失败时，先查询该 Computer 的近期任务并核对时间与范围，恢复实际 taskId，不盲目重新创建。

可下载后生成链接：

```sh
tutti-ops --admin-url https://admin.tutti.sh --mode read computer log-recalls download-url --computer-id "COMPUTER_ID" --task-id "TASK_ID"
```

该命令虽使用 HTTP POST，注册表将其分类为 read，不需要创建召回的 write 操作确认。成功返回 `data.downloadUrl`（字段拼写以现场返回为准）。它只生成链接，不下载、解包或读取文件，也没有 `--output` 参数。

## 下载、校验和读取

使用已授权的 HTTP 下载工具将日志包保存到会话临时目录，对象存储请求不附加管理 Token；`static.tutti.sh` 会以 403 拒绝 Python 默认 User-Agent，需显式设置。按任务返回的包 SHA256 校验；未提供校验值时明确记录缺口。独立目录安全解包，读取 `manifest.json` 和故障时间内的相关日志，保留必要堆栈上下文。

再次核对 Computer、版本、实际时间覆盖、文件清单、未知时间戳行及截断状态；请求范围或任务可下载状态不能代替清单覆盖检查。链接过期时为同一仍在保留期内的 taskId 重新生成链接，不创建重复任务。签名链接不回填飞书，回填任务标识、必要日志附件与证据缺口。

完成条件沿用 [远端日志召回](computer-logs.md#远端复用-tutti-日志召回)：日志包已下载、校验、读取并保存证据，或记录了具体失败与恢复条件。帮助、schema、预览、任务创建或链接生成都不表示已取得日志。本次只验证安装与离线能力，尚未执行真实远端采集。

核对入口：已安装包的 `dist/{index.js,config.js}`、`dist/operations/registry.js`、`dist/core/{commands.js,executor.js,input.js}`；服务端范围、状态和响应字段见 `tutti-server/api/sandbox/v2/computer_runtime_log.proto`。升级后重新发现实际命令与协议。
