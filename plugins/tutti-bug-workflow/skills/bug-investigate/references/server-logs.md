# Server 日志

每次提 Bug 都拉 tutti-server 日志。固定的是来源（AWS CloudWatch 的 tutti-server 日志），不固定的是拉哪些——按这次的 request id 去找。

## 日志在哪里

- 日志组：`/aws/containerinsights/nexight-ojo-us-east-1/application`，区域 `us-east-1`，复用本机 AWS CLI 已有的身份（由 bug-setup 准备）。
- 容器 `tutti-server`；Kubernetes namespace 区分环境：`tutti` 是生产，`lane-ppe-*` 是 PPE，其他 `lane-*` 是预览环境。
- 访问日志是 logfmt，`log_type=api_access`，包含成功和失败的请求：`request_id`、`route`、`method`、`path`、`status_code`、`latency_ms`、`error_message`、`task_id`、`service.version`。**不含用户 ID**，所以不能按用户查，只能按这次请求的 `request_id` 找。

## request id 从哪来

格式 `20261010T094855Z-<uuid>`，服务端在响应头 `x-request-id` 里返回：

- Web 日志：`collect_server.py --web-logs` 直接从 `web-logs.log` 或 QA 导出的诊断包 zip（`logs.jsonl` 的 `requestId`）里提取；
- 也可以用 `--request-id` 直接传；
- 没有 request id 时，用路径里的业务 ID 兜底：`--path-contains <房间 ID>`、`<Computer ID>`。

## 怎么拉

```sh
python3 scripts/collect_server.py --question-time <question_time> \
  --web-logs <web-logs.log 或诊断包 zip> [--request-id <id> ...] [--path-contains <ID> ...] \
  [--before-minutes 10] [--after-minutes 10] --output-dir $TMP/server
```

脚本按 20 个一批用 CloudWatch Insights 查询，轮询到完成，按时间排序去重，写出 `server-logs.log`（首行 metadata：时间窗、日志组、namespace、环境、命中的 request id 数、是否截断）。

- `status: captured`：取到日志；`namespaces`／`environments` 写进「环境与版本」，`service.version` 写进版本信息。
- `status: empty`：时间窗内没有匹配，常见原因是 request id 来自别的时间或页面已刷新；放宽 `--before-minutes`／`--after-minutes` 或换用 `--path-contains` 再试一次。
- AWS SSO 登录过期：脚本自动运行 `aws sso login`（本机弹出浏览器，用户点「允许」），成功后重试，结果带 `login: {triggered: true, ok: true}`。无人值守时加 `--no-login`。
- `status: blocked`：`reason_kind: login_expired` 表示自动登录也没完成（10 分钟没授权、没有配置 SSO），写清用户要做的一步；其他是权限或网络问题，写进回复交给维护方，不让用户找日志。

## 上传

`server-logs.log` 原样上传到「截图、视频、日志」。查询原始结果不上传。
