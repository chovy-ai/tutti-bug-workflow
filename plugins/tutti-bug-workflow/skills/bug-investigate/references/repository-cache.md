# 固定代码缓存

缓存的初始化与预热由 bug-setup 负责。

## 位置与更新

默认共享数据目录下各有一个 bare Git 仓库：

```text
~/.local/share/bug-workbench/repositories/tutti.git
~/.local/share/bug-workbench/repositories/tutti-server.git
```

配置 `repositories[].cache_path` 相对数据目录解析；必须位于该数据目录内。更换共享数据目录用 `--data-dir` 或已有数据目录环境变量。所有使用者应使用同一个数据目录，插件更新只换源码，保留代码缓存。缓存只用于加速拉取，不是流程状态。

每次分析前运行：

```sh
python3 PLUGIN_SOURCE/skills/bug-investigate/scripts/sync_code.py --data-dir DATA_DIR
```

首次创建缓存；后续对同一缓存执行 fetch，只下载远端缺少的 Git 对象。命令仍需联网检查 main 的最新版本；没有新提交时复用已有内容。缓存保留 main 历史，便于调查回归和使用 blame。缓存只存 Git 数据，每个 Bug 的源码工作区通过 worktree 共享这些对象。

脚本验证仓库名、路径、bare 类型和远端身份；同一数据目录的同步通过系统文件锁串行执行。锁等待超过 30 秒会返回可重试错误，进程退出释放锁。每次成功返回两仓库 SHA、获取时间、缓存路径及独立 snapshot_ref，并保存在 `repositories/sync-runs/`。快照引用保留该提交，后续 main 前进不会改变本轮代码版本。

网络、权限、缓存身份或配置错误时返回失败，已有缓存保留。两个仓库都成功才能说明本轮已取得最新 main；不能把旧缓存当作本轮最新版本。认证继续使用系统 Git 凭证存储，不保存到插件配置或分发包。

## Bug 工作区

成功同步后，使用返回的 cache_path 与 SHA 创建隔离工作树。例如下面的占位值须替换为已验证的真实值：

```sh
git -C CACHE_PATH worktree add -b codex/BUG_SUMMARY-analysis-RUN_ID WORKTREE_PATH SHA
```

提 Bug（无状态）时，工作树作为临时文件放在会话临时目录，以 detached HEAD 固定在返回的 SHA：`git -C CACHE_PATH worktree add --detach $TMP/worktrees/REPOSITORY SHA`，排查结束后 `git -C CACHE_PATH worktree remove $TMP/worktrees/REPOSITORY`。SHA 写进飞书「代码基线」。对每个仓库独立操作，不覆盖或重置已有工作树。分析、方案与修复读取记录的工作区和 SHA，业务修改不写入共享缓存本体。执行分支继续使用 `codex/<bug-summary>` 约定，并遵守方案批准与版本核对。

worktree 仍需在磁盘检出源码文件，但不重新克隆或下载相同的 Git 对象。依赖安装、Git LFS 内容和 submodule 是独立准备步骤，按实际仓库要求处理。缓存、快照和工作树的清理单独进行，本版同步不自动删除历史运行。
