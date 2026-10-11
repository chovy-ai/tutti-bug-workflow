# 修复工作区

每次修复从远端最新 main 切出独立 worktree，修复结束推送后解除，不保留本地工作区。根因分析用的全局检出由 `$tutti-bug-workflow:bug-solution` 维护，这里不碰它。

## 位置

| 配置项 | 默认路径 | 用途 |
|---|---|---|
| `repositories[].cache_path` | `repositories/tutti.git` | bare 缓存，和分析共用 |
| — | `worktrees/<仓库>/<分支，/ 换成 ->` | 本次修复的 worktree |

路径都相对数据目录（默认 `~/.local/share/bug-workbench`）。

## 命令

```sh
python3 scripts/repos.py start  --repo tutti --branch codex/room-name-sync
python3 scripts/repos.py finish --path <worktree>
python3 scripts/repos.py remove --path <worktree> [--discard]
```

| 命令 | 做什么 | 拒绝的情况 |
|---|---|---|
| `start` | fetch 远端 main，从最新 SHA 建新分支和 worktree | 分支名不合法或是 main；分支已在缓存或远端存在；路径已存在 |
| `finish` | fetch main，推送分支，核对远端 HEAD，删除 worktree 和本地分支 | 有未提交改动；相对 main 没有新提交；推送后远端不一致（worktree 保留） |
| `remove` | 不推送，直接删除 worktree 和本地分支 | 有未提交改动或未推送的提交，除非加 `--discard` |

- 只接受 `start` 建的 worktree（位于数据目录 `worktrees/` 下且属于配置的仓库缓存）。
- 推送用系统 Git 凭证，需要对仓库有写权限；不强推。
- 依赖安装、构建产物都在 worktree 里，随 worktree 一起删除。
