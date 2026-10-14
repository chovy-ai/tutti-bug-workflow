# AGENTS.md

## 目录按 Skill 划分

插件 `plugins/tutti-bug-workflow/` 的内容按 Skill 划分：每个 Skill 的参考文档、脚本、模板、配置和测试都放在自己的目录下。

```text
plugins/tutti-bug-workflow/
  skills/<skill>/
    SKILL.md
    agents/openai.yaml
    references/   本 Skill 读取的文档
    scripts/      本 Skill 调用的脚本
    assets/       本 Skill 使用的模板、图片
    config/       本 Skill 专用的配置（如有）
    tests/        本 Skill 脚本的测试
  disabled-skills/ 暂时屏蔽、插件不加载的 Skill（bug-solution、bug-execute），恢复方式见其 README
  scripts/        插件级：插件校验
  config/         插件级：运行配置模板 workbench.example.json
  plugin.json, .codex-plugin/, mcp.json, .mcp.json, README.md
```

规则：

1. **Skill 之间不互相引用文件。** 一个 Skill 的 SKILL.md、references、scripts 只链接或调用本 Skill 目录下的文件。多个 Skill 需要同一份内容时，各自保留一份，并只保留与本 Skill 相关的部分；接受重复，避免耦合。例如 `feishu.py` 由各 Skill 按自己的读写需要各自维护。
2. **需要另一个 Skill 的能力时，引用 Skill 而不是文件**，例如「工具安装与认证由 `$tutti-bug-workflow:bug-setup` 处理」。
3. **使用和准备分开写。** 工具的安装、认证、授权写在 bug-setup；如何使用写在使用它的 Skill。
4. **插件级目录只放插件本身的东西**：插件清单、MCP 注册文件（`mcp.json`、`.mcp.json`，注册官方 `chrome-devtools-mcp`）、`scripts/validate_plugin.py`、各 Skill 共同读取的运行配置模板 `config/workbench.example.json`、README。不要在插件级新增 `references/`、`assets/` 或业务脚本。
5. Skill 内脚本的路径写成相对 Skill 目录（如 `scripts/feishu.py`），或插件源码下的完整路径（如 `PLUGIN_SOURCE/skills/bug-setup/scripts/workbench.py`）。

## 测试

```sh
cd plugins/tutti-bug-workflow
for skill in skills/bug-investigate skills/bug-setup disabled-skills/bug-solution disabled-skills/bug-execute; do
  python3 -m unittest discover -s $skill/tests -t $skill/tests
done
python3 scripts/validate_plugin.py
```

`skills/*/tests/fixtures-*.py` 是测试替身，不要作为测试文件直接运行。
