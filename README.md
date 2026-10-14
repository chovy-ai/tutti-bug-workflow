# tutti-bug-workflow

插件源码位于 [plugins/tutti-bug-workflow](plugins/tutti-bug-workflow/README.md)，包含三个业务场景：提 Bug、根因与方案、修复与验证。首次配置由公共初始化 Skill 完成。

这是本地源码与私有分发目录。0.2.3 默认绑定飞书 Bug 管理表及 tutti / tutti-server / tsh-websocket 的 main，三个场景共用同一条记录、不保留本地档案。QA 提 Bug 带全现场后在当前 Tutti Room 建 Task（`tutti-task` 分支，不写飞书表）；RD 在根因与方案场景中分析根因、协商方案并记录批准；修复从最新 main 切 worktree，推送并提 PR 后解除。技术接入和权限缺口由维护侧处理。Computer 定位使用最新 main 中的页面目录能力，存在多个候选时请 QA 确认；本机读取已确认的文件，远端使用 Tutti 日志召回。setup 复用已有 tutti-ops，缺少时执行 `npm install -g @tutti-os/tutti-ops-cli`，并准备 AWS CLI v2；完整 Setup 先完成工具安装，安装结束后立即进入授权，主动检查并补齐所需认证与权限，发起适用登录、引导本人授权后复查实际访问；只梳理或明确跳过时遵循用户范围。Web 日志接入和带截图的启用引导见插件 README。飞书事件监听尚未接入。

工具可按 QA 分析、RD 方案、修复验证分组准备，详见 [场景工具 Setup](plugins/tutti-bug-workflow/skills/bug-setup/references/tool-setup.md)。

完整的每步准备条件见 [Setup Skill](plugins/tutti-bug-workflow/skills/bug-setup/SKILL.md)，支持先梳理现状和待决策项，再按确定的方式初始化。

安装时将本目录作为本地 marketplace 注册，再安装插件：

```sh
codex plugin marketplace add /absolute/path/to/bug-workbench-plugin
codex plugin add tutti-bug-workflow@tutti-bug-workflow-local
```

将路径替换为本目录的真实路径。安装后在新的 Codex 会话中选择相应 Skill。以上命令已按当前本地 Codex CLI 的帮助确认；桌面可见性以实际安装结果为准。

Web 日志使用 QA 在 Tutti「设置 → 诊断」导出的诊断包，见 [插件 Web 日志文档](plugins/tutti-bug-workflow/skills/bug-investigate/references/web-logs.md)。
