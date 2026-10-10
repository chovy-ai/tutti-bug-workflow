# 用 tutti-ops 获取远端 Computer 日志

提 Bug 时由 `scripts/collect_computer.py` 自动执行本页的定位已有任务、创建、等待、生成链接、下载与校验；本页供脚本失败排查或手动操作时参考。这是 [Computer 日志获取](computer-logs.md) 中远端日志召回协议的 CLI 入口；本机继续读取已确认的文件。2026-09-30 核对了本机实际安装的 npm 包 `@tutti-os/tutti-ops-cli@0.1.6` 的 Computer 帮助、能力清单、六个操作的 schema，以及零网络创建与下载链接预览。

tutti-ops 的安装、Token 与权限由 bug-setup 准备；认证或权限失败写进「分析根因」的「待确认」交给维护方。

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
