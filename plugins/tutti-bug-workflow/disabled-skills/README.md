# 暂时屏蔽的 Skills

`bug-solution`（RD 定时根因分析与方案）和 `bug-execute`（定时修复与部署）暂时不开放。它们放在这里而不是 `skills/` 下，插件只从 `skills/` 加载 Skill，所以安装插件时只有 bug-investigate 和 bug-setup；源码和测试原样保留。

恢复时：

1. 把两个目录移回 `skills/`。
2. 在 `skills/bug-setup/scripts/prepare.py` 和 `tool_setup.py` 的 `ENABLED_SCENES` 里加回 `solution`、`execute`，去掉 bug-setup 测试里对应的 `@unittest.skip`。
3. 恢复 `skills/bug-setup/SKILL.md` 的选场景步骤，以及 `scripts/validate_plugin.py` 的 `SCENES`、插件清单和 README 里这两个 Skill 的说明。
