# tutti-bug-workflow

插件源码位于 [plugins/tutti-bug-workflow](plugins/tutti-bug-workflow/README.md)。四个 Skill：QA 提 Bug（bug-investigate）、根因分析（bug-analyze）、修复与部署（bug-execute）和环境准备（bug-setup）。Bug 记录在 Multica issue，三个业务 Skill 由本机 Multica 的三个 Agent 执行、靠分配 issue 交接。

QA 提 Bug 带全现场后在 Multica 登记 issue，自动分配给分析 Agent；分析 Agent 拉最新代码给出根因和方案，等 RD 评审；RD 认可后分配给修复 Agent，修复、提 PR、部署 PPE、自验证，结果和截图回复到 issue。setup 按场景安装工具、补默认配置，把技能同步到 Multica 的三个 Agent，引导登录、Token 和 Chrome 授权后复查。提 Bug 不拉服务端日志、不用 AWS，只记 request id。

完整的每步准备条件见 [Setup Skill](plugins/tutti-bug-workflow/skills/bug-setup/SKILL.md)，支持先梳理现状和待决策项，再按确定的方式初始化。

安装时将本目录作为本地 marketplace 注册，再安装插件：

```sh
codex plugin marketplace add /absolute/path/to/bug-workbench-plugin
codex plugin add tutti-bug-workflow@tutti-bug-workflow-local
```

将路径替换为本目录的真实路径。安装后在新的 Codex 会话中选择相应 Skill。以上命令已按当前本地 Codex CLI 的帮助确认；桌面可见性以实际安装结果为准。

Web 日志使用 QA 在 Tutti「设置 → 诊断」导出的诊断包，见 [插件 Web 日志文档](plugins/tutti-bug-workflow/skills/bug-investigate/references/web-logs.md)。
