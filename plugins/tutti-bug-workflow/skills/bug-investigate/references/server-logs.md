# Server 日志

每次提 Bug 都拉 tutti-server 日志。固定的是来源（AWS CloudWatch 的 tutti-server 日志），不固定的是拉哪些——按这次的 request id 去找。

## 日志在哪里

- 日志组：`/aws/containerinsights/nexight-ojo-us-east-1/application`，区域 `us-east-1`，复用本机 AWS CLI 已有的身份（由 bug-setup 准备）。
- 容器 `tutti-server`；Kubernetes namespace 区分环境：`tutti` 是生产，`lane-ppe-*` 是 PPE，其他 `lane-*` 是预览环境。
- 访问日志是 logfmt，`log_type=api_access`：`request_id`、`route`、`method`、`url_path`、`status_code`、`latency_ms`、`error_message`、`task_id`、`service.version`。**不含用户 ID**，所以不能按用户查，只能按这次请求的 `request_id` 找。

## request id 从哪来

格式 `20261010T094855Z-<uuid>`。脚本按顺序合并三种来源：

1. **直接给的**：`--request-id`、`--request-ids-file`，例如从 Computer 的 `desktopd.log` 里读到的 `request_id`（见 [Computer 日志里的 request id](computer-logs.md#日志里的-request-id)）。
2. **Web 日志里记下的**：`--web-logs` 从 `web-logs.log` 或诊断包 zip 里提取。新版 Tutti Web 的每条 HTTP 记录都带网关分配的 `requestId`（响应头 `x-zk-request-id`）；5 秒内重复的请求折叠成一条时，全部 id 保留在 `requestIds`。这是主要来源。
3. **按请求对上的**：只用于**没有 request id 的 HTTP 记录**（旧版 Web 的记录都是 `requestId: null`）。脚本取时间窗内这类失败的 Web 请求（没有失败时取离 `question_time` 最近的请求，默认最多 40 个），到访问日志里找 **method、路径、状态码都相同、时间最接近**的那条，用它的 `request_id`。页面请求的 `/api/desktop/v2/...` 对应服务端的 `url_path=/v2/...`；desktopd 等本机请求不进 tutti-server，自动跳过。自带 id 的记录不参与匹配。

再拿得到的全部 request id 拉**这些请求的所有日志行**（访问日志和业务日志）。

`--path-contains <房间 ID>`／`<Computer ID>` 是附加的宽查询：会带回该时间窗内路径含这些 ID 的全部请求（常有几百条），只在需要看整段上下文、或上面三种来源都对不上时再加，不要默认加。

## 怎么拉

```sh
python3 scripts/collect_server.py --question-time <question_time> \
  --web-logs <web-logs.log 或诊断包 zip> [--request-id <id> ...] [--path-contains <ID> ...] \
  [--before-minutes 10] [--after-minutes 10] --output-dir $REPORT/server
```

脚本按 20 个一批用 CloudWatch Insights 查询，轮询到完成，按时间排序去重，写出 `server-logs.log`（首行 metadata）。结果里要看的字段：

| 字段 | 含义 |
|---|---|
| `request_ids`、`matched_request_ids` | 用到的 request id 数、实际查到日志的数 |
| `request_ids_in_web_logs`、`web_http_requests`、`web_requests_with_id`、`web_requests_checked`、`web_requests_matched` | Web 日志里自带的 id 数、发往 tutti-server 的请求数、其中自带 id 的请求数、没有 id 而拿去对的请求数、对上的数 |
| `correlated_requests` | 对上的请求：时间、method、路径、状态码、`request_id` |
| `web_failures_not_in_server_logs` | 页面上失败、但 tutti-server 访问日志里没有的请求（常见是网关限流 429、网络中断）：说明请求没到服务端 |

- `status: captured`：取到日志；`namespaces`／`environments` 写进「环境与版本」，`service.version` 写进版本信息；把 `correlated_requests` 里与故障相关的请求（时间、路径、状态码、`request_id`）和 `web_failures_not_in_server_logs` 写进「问题上下文」，RD 据此直接定位。
- `status: empty`：时间窗内没有匹配。Web 日志自带的 id 也查不到日志时，先核对 `question_time` 时区和时间窗；看 `web_requests_checked`：为 0 且 `web_requests_with_id` 也为 0，说明 Web 日志在时间窗内没有发往 tutti-server 的请求（核对 `question_time` 时区、页面是否已刷新）；不为 0 但都没对上，多半是请求没到服务端（看 `web_failures_not_in_server_logs`）或时间偏了，放宽 `--before-minutes`／`--after-minutes` 再试一次，仍为空再加 `--path-contains`。
- AWS SSO 登录过期：脚本自动运行 `aws sso login`（本机弹出浏览器，用户点「允许」），成功后重试，结果带 `login: {triggered: true, ok: true}`。无人值守时加 `--no-login`。
- `status: blocked`：`reason_kind: login_expired` 表示自动登录也没完成（10 分钟没授权、没有配置 SSO），写清用户要做的一步；其他是权限或网络问题，写进回复交给维护方，不让用户找日志。

## 上传

`server-logs.log` 原样上传到「截图、视频、日志」。查询原始结果不上传。
