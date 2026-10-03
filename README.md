# tutti-bug-workflow

插件源码位于 [plugins/tutti-bug-workflow](plugins/tutti-bug-workflow/README.md)，包含三个业务场景：问题分析、方案协商、修复与验证。首次配置由公共初始化 Skill 完成。

这是本地源码与私有分发目录。0.1.20 默认绑定指定飞书 Bug 表、三个状态视图及 tutti/tutti-server 的 main，并使用固定代码缓存增量同步。普通 QA 上报默认登记并自行分析代码与可用日志，完成本轮排查后反馈结论或必要的现场追问；技术接入和权限缺口由维护侧处理。Computer 定位使用最新 main 中的页面目录能力，存在多个候选时请 QA 确认；本机读取已确认的文件，远端使用 Tutti 日志召回。setup 复用已有 tutti-ops，缺少时执行 `npm install -g @tutti-os/tutti-ops-cli`，并准备 AWS CLI v2；授权允许以后完成，默认不启动登录或身份查询。Web 日志接入和带截图的启用引导见插件 README。飞书事件监听尚未接入。

工具可按 QA 分析、RD 方案、修复验证分组准备，详见 [场景工具 Setup](plugins/tutti-bug-workflow/references/tool-setup.md)。

完整的每步准备条件见 [Setup Skill](plugins/tutti-bug-workflow/skills/bug-setup/SKILL.md)，支持先梳理现状和待决策项，再按确定的方式初始化。

安装时将本目录作为本地 marketplace 注册，再安装插件：

```sh
codex plugin marketplace add /absolute/path/to/bug-workbench-plugin
codex plugin add tutti-bug-workflow@tutti-bug-workflow-local
```

将路径替换为本目录的真实路径。安装后在新的 Codex 会话中选择相应 Skill。以上命令已按当前本地 Codex CLI 的帮助确认；桌面可见性以实际安装结果为准。
