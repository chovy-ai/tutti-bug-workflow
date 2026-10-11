# 代码检出

根因分析用全局代码检出，所有 Bug 共用；修复不在这里进行，`$tutti-bug-workflow:bug-execute` 会从远端 main 另切 worktree。

## 位置

数据目录（默认 `~/.local/share/bug-workbench`）下每个仓库两份：

| 配置项 | 默认路径 | 用途 |
|---|---|---|
| `repositories[].cache_path` | `repositories/tutti.git` | bare 缓存，只存 Git 对象 |
| `repositories[].checkout_path` | `repositories/tutti` | 全局检出，缓存的一个 detached worktree，跟随远端 main |

## 同步

```sh
python3 scripts/repos.py sync              # 全部仓库
python3 scripts/repos.py sync --repo tutti # 只同步一个
```

- 缓存不存在时初始化，之后每次只 fetch 远端缺少的对象，再把检出移到最新 main 的 SHA。
- 同一数据目录的同步加文件锁串行执行，等待超过 60 秒返回可重试错误。
- 检出有本地改动时拒绝同步，不会覆盖；把改动移走后再跑。
- 网络、权限或缓存身份不符时返回失败，已有检出保持原样；这时不能把旧检出当作最新 main。

## 使用

- 只读：阅读、搜索、`git log`、`git blame`、`git show <线上版本>`。
- 不在检出里改代码、切分支、安装依赖或生成文件；最小复现复制到 `$TMP` 里做。
- 证据里的代码位置写成 `仓库@sha 路径:行号`，sha 用同步返回的值。
