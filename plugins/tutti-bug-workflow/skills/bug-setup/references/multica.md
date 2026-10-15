# Multica 接入

三个业务 Skill 都以 Multica issue 作为 Bug 的唯一记录，分别由 Multica 里的三个 Agent 执行；Agent 绑定本机的 Codex runtime，在这台机器上运行，直接复用本机的 Chrome、gh、tutti-ops 登录态和代码缓存。本页只讲准备；各 Skill 怎么读写 issue 写在各自的 SKILL.md。

## 配置

数据目录 `config.json` 的 `multica`（`prepare.py fix` 补齐默认值）：

| 字段 | 默认值 | 说明 |
|---|---|---|
| `profile` | `desktop-api.multica.ai` | `multica --profile` 的名称；Multica 桌面端登录后写在 `~/.multica/profiles/<profile>/` |
| `workspace_id` | 空 | 空时用 profile 里唯一的 workspace；有多个时必须填 |
| `project` | `Bug列表` | Bug issue 所在项目的名称（或 ID） |
| `agents.investigate` | `噜噜Bug守门员` | 登记 Bug（bug-investigate） |
| `agents.analyze` | `噜妹Bug分析师` | 根因分析（bug-analyze） |
| `agents.execute` | `牛牛Bug解决专员` | 修复与部署（bug-execute） |

Agent 名称和项目名称跟 Multica 里实际的一致即可，改名后改这里，再同步一次。

## 本人在 Multica 里做的事

1. 安装并登录 Multica 桌面端，确认本机 daemon 在运行（`multica --profile <profile> daemon status`）。
2. 新建项目 `project`。
3. 新建三个 Agent，运行环境都选**本机的 Codex runtime**（`multica --profile <profile> runtime list` 里在线的 `codex`）；名称与配置一致。

Agent 和项目只由本人创建，脚本不会创建。

## 同步

```sh
python3 scripts/multica.py status          # 只读：登录、项目、Agent 与 runtime、技能是否与插件源码一致
python3 scripts/multica.py sync --prune    # 同步
```

`sync` 把插件源码里的 `bug-investigate`、`bug-analyze`、`bug-execute` 写成 workspace 技能（SKILL.md 和文本文件，不含 `tests/`；源码已删除的文件在 workspace 里也删除），给每个 Agent 只分配它自己的技能，并写入 Agent 指令（指令里带着交接对象的名称）。`--prune` 同时删除已不再使用的旧技能（如 `bug-solution`）。插件更新后再跑一次 `sync`；`prepare.py fix` 发现不一致时会自动执行。

`multica.py` 总是显式带 `--profile` 和 `--workspace-id`，并忽略环境里的 `MULTICA_*` 变量，在 Multica 任务里运行也不会写错 workspace。

## 交接

```text
QA 建 issue 分配给 investigate（或直接对它说「记个 bug」）
  → investigate 登记、发现场，分配给 analyze
  → analyze 回复根因与方案，状态 in_review
  → RD 评审：评论追问（analyze 在同一 issue 补充），认可后分配给 execute
  → execute 修复、部署 PPE、自验证，回复结果与截图，状态 in_review（失败 blocked）
  → QA 验收，置为 done
```

分配 issue 就会让对应 Agent 开始执行；分析之后必须由 RD 手动分配给修复 Agent，不自动修复。
