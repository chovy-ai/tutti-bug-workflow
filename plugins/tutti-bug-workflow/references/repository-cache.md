# 固定代码缓存

## 位置与更新

默认共享数据目录下各有一个 bare Git 仓库：

```text
~/.local/share/bug-workbench/repositories/tutti.git
~/.local/share/bug-workbench/repositories/tutti-server.git
```

配置 `repositories[].cache_path` 相对数据目录解析；必须位于该数据目录内。更换共享数据目录用 `--data-dir` 或已有数据目录环境变量。所有使用者应使用同一个数据目录，插件更新只换源码，保留代码缓存与 Bug 档案。

每次分析前运行：

```sh
python3 PLUGIN_SOURCE/scripts/sync_code.py --data-dir DATA_DIR
```

首次创建缓存；后续对同一缓存执行 fetch，只下载远端缺少的 Git 对象。命令仍需联网检查 main 的最新版本；没有新提交时复用已有内容。缓存保留 main 历史，便于调查回归和使用 blame。缓存只存 Git 数据，每个 Bug 的源码工作区通过 worktree 共享这些对象。

脚本验证仓库名、路径、bare 类型和远端身份；同一数据目录的同步通过系统文件锁串行执行。锁等待超过 30 秒会返回可重试错误，进程退出释放锁。每次成功返回两仓库 SHA、获取时间、缓存路径及独立 snapshot_ref，并保存在 `repositories/sync-runs/`。快照引用保留该提交，后续 main 前进不会改变本轮代码版本。

网络、权限、缓存身份或配置错误时返回失败，已有缓存保留。两个仓库都成功才能说明本轮已取得最新 main；不能把旧缓存当作本轮最新版本。认证继续使用系统 Git 凭证存储，不保存到插件配置或分发包。

## 首次预热与兼容

推荐使用独立 bare 缓存。配置已有仓库的 `local_path` 时，脚本先核对其 origin 与指定仓库一致，将本地 origin/main 可达的已提交对象复制到新缓存，再向实际远端同步。只读取已有检出，不包含未提交改动；缓存不依赖本地仓库的 alternates，后续原工作区移动或删除仍可独立使用。未找到可用本地对象时直接从远端初始化。

兼容方式可继续在指定的已有仓库 fetch main，再创建隔离 worktree，同样无需重复 clone；使用该方式须核对远端、固定 SHA 并保留现有改动。它会与日常开发共享仓库维护状态，默认流程采用独立缓存。

## Bug 工作区

成功同步后，使用返回的 cache_path 与 SHA 创建隔离工作树。例如下面的占位值须替换为已验证的真实值：

```sh
git -C CACHE_PATH worktree add -b codex/BUG_SUMMARY-analysis-RUN_ID WORKTREE_PATH SHA
```

工作树放在共享数据目录的 `bugs/BUG_ID/worktrees/RUN_ID/REPOSITORY`，记录到档案。对每个仓库独立操作。已有分支或工作树使用唯一新运行 ID，不覆盖或重置现有内容。分析、方案与修复读取记录的工作区和 SHA，业务修改不写入共享缓存本体。执行分支继续使用 `codex/<bug-summary>` 约定，并遵守方案批准与版本核对。

worktree 仍需在磁盘检出源码文件，但不重新克隆或下载相同的 Git 对象。依赖安装、Git LFS 内容和 submodule 是独立准备步骤，按实际仓库要求处理。缓存、快照和工作树的清理单独进行，本版同步不自动删除历史运行。
