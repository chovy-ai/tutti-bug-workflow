# tutti-bug-workflow

插件源码位于 [plugins/tutti-bug-workflow](plugins/tutti-bug-workflow/README.md)。四个 Skill：QA 提 Bug（bug-investigate）、验收打回（bug-reopen）、修复与部署（bug-execute）和环境准备（bug-setup），只对接 Tutti 任务系统，不用飞书表，也没有定时任务。

QA 提 Bug 带全现场后，用全局 `tutti-cli`（账号登录版）在指定 Room 建 Task，再交给该 Room 的 Agent 分析根因；Room 按 Room ID、房间名或用户名从本地房间里找。验收不通过时 bug-reopen 和提 Bug 一样采集这一轮的现场，评论到原 Task（截图和日志作为评论附件，不改原描述），用 `tutti-cli task status` 把 Task 改回待办，再交给该 Room 的 Agent 重新分析；QA 只要发已有 Task 链接和截图说「这里还有问题」即可。bug-execute 由 RD 指定一条 Task 和认可的方案，修复、提 PR、部署 PPE、自验证，结果回复到 Task。setup 按场景安装工具、补默认配置，引导登录、Token 和 Chrome 授权后复查。提 Bug 不拉服务端日志、不用 AWS，只记 request id。

完整的每步准备条件见 [Setup Skill](plugins/tutti-bug-workflow/skills/bug-setup/SKILL.md)，支持先梳理现状和待决策项，再按确定的方式初始化。

安装时将本目录作为本地 marketplace 注册，再安装插件：

```sh
codex plugin marketplace add /absolute/path/to/bug-workbench-plugin
codex plugin add tutti-bug-workflow@tutti-bug-workflow-local
```

将路径替换为本目录的真实路径。安装后在新的 Codex 会话中选择相应 Skill。以上命令已按当前本地 Codex CLI 的帮助确认；桌面可见性以实际安装结果为准。

Web 日志优先通过 `download_web_logs` 触发本机 Chrome 直接下载完整 JSON 文件，工具仅返回文件元数据，日志正文不经过 LLM。`merge_web_logs.py --download` 在本地校验文件并整理成 `web-logs.log`，再按需提取请求和相关片段；不再提供分页读取或分页导入入口。WebMCP 不可用时，使用 QA 在 Tutti「设置 → 诊断」导出的诊断包，见 [插件 Web 日志文档](plugins/tutti-bug-workflow/skills/bug-investigate/references/web-logs.md)。
