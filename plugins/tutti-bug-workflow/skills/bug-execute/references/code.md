# 修复工作区

每次修复从远端分支切出独立 worktree（新修复用最新 origin/main，重试时用远端已有的修复分支），修复后推送、提 PR 到 main、部署 PPE，最后移除 worktree，不保留本地工作区。根因分析用的固定检出（`repositories/<仓库名>`，分析 Agent 用）这里不碰。

## 位置与命名

| 项 | 值 |
|---|---|
| bare 缓存 | `repositories/<仓库>.git`（`repositories[].cache_path`） |
| 仓库 | tutti（Web、Computer）、tutti-server（Server）、tsh-websocket（WebSocket），见 `repositories` |
| 分支 | `codex/bug-<issue 编号小写>`（`deploy.branch_prefix`，`deploy.py fix-names` 给出），各仓库同名 |
| worktree | `worktrees/<仓库>/<分支，/ 换成 ->` |

路径都相对数据目录（默认 `~/.local/share/bug-workbench`）。

## 命令

```sh
python3 scripts/repos.py start  --repo tutti --branch <branch>
python3 scripts/repos.py push --path <worktree>
python3 scripts/repos.py remove --path <worktree>          # PPE 部署结束后
python3 scripts/repos.py remove --path <worktree> [--discard]
```

| 命令 | 做什么 | 拒绝的情况 |
|---|---|---|
| `start` | fetch 远端 main；分支不存在就从最新 main 新建，**远端已有同名分支（重试）就接着它**，返回 `resumed`、`behind_main` | 分支名不合法或是 main；本地缓存里已有同名分支（上次没收尾，先 `remove`）；路径已存在 |
| `push` | fetch main，推送分支，核对远端 HEAD；worktree 保留到 PPE 部署结束 | 有未提交改动；相对 main 没有新提交；推送后远端不一致 |
| `remove` | PPE 部署结束后（或放弃修复时）删除 worktree 和本地分支 | 有未提交改动或未推送的提交，除非加 `--discard` |

- 重试时 `behind_main > 0` 先 rebase 到最新 main 再继续；rebase 后推送需要 `git push --force-with-lease`，由会话在 worktree 里执行后再 `push`。
- 推送用系统 Git 凭证，需要写权限。
- 依赖安装、构建产物都在 worktree 里，随 worktree 一起删除。
