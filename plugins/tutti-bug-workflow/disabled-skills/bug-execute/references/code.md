# 修复工作区

每次修复从远端最新 main 切出独立 worktree，推送后解除，不保留本地工作区。根因分析用的全局检出由 `$tutti-bug-workflow:bug-solution` 维护，这里不碰它。

## 位置与命名

| 项 | 值 |
|---|---|
| bare 缓存 | `repositories/<仓库>.git`（`repositories[].cache_path`），和分析共用 |
| 仓库 | tutti（Web、Computer）、tutti-server（Server）、tsh-websocket（WebSocket），见 `repositories` |
| 分支 | `codex/bug-<record_id 小写>`（`deploy.branch_prefix`），各仓库同名 |
| worktree | `worktrees/<仓库>/<分支，/ 换成 ->` |

路径都相对数据目录（默认 `~/.local/share/bug-workbench`）。

## 命令

```sh
python3 scripts/repos.py start  --repo tutti --branch codex/bug-<record_id>
python3 scripts/repos.py finish --path <worktree>
python3 scripts/repos.py remove --path <worktree> [--discard]
```

| 命令 | 做什么 | 拒绝的情况 |
|---|---|---|
| `start` | fetch 远端 main；分支不存在就从最新 main 新建，**远端已有同名分支（重试）就接着它**，返回 `resumed`、`behind_main` | 分支名不合法或是 main；本地缓存里已有同名分支（上次没收尾，先 `remove`）；路径已存在 |
| `finish` | fetch main，推送分支，核对远端 HEAD，删除 worktree 和本地分支 | 有未提交改动；相对 main 没有新提交；推送后远端不一致（worktree 保留） |
| `remove` | 不推送，直接删除 worktree 和本地分支 | 有未提交改动或未推送的提交，除非加 `--discard` |

- 重试时 `behind_main > 0` 先 rebase 到最新 main 再继续；rebase 后推送需要 `git push --force-with-lease`，由会话在 worktree 里执行后再 `finish`。
- 推送用系统 Git 凭证，需要写权限。
- 依赖安装、构建产物都在 worktree 里，随 worktree 一起删除。
