# 暂时屏蔽的 Skills

`bug-solution`（RD 定时根因分析与方案）暂时不开放。它放在这里而不是 `skills/` 下，插件只从 `skills/` 加载 Skill，所以安装插件时只有 bug-investigate、bug-execute 和 bug-setup；源码和测试原样保留。屏蔽期间，分析根因、修复方式、验收标准由 RD 直接填在飞书 bug 单上，方案状态改成「已批准」后由 bug-execute 接手。

恢复时：

1. 把目录移回 `skills/`。
2. 在 `skills/bug-setup/scripts/prepare.py` 和 `tool_setup.py` 的 `ENABLED_SCENES` 里加回 `solution`，去掉 bug-setup 测试里对应的 `@unittest.skip`。
3. 恢复 `skills/bug-setup/SKILL.md` 选场景里的「定时分析」，以及 `scripts/validate_plugin.py` 的 `SCENES`、插件清单和 README 里这个 Skill 的说明。
