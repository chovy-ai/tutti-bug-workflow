# 代码缓存与检出

Setup 保存仓库配置并可按需预热；分析时的同步由 bug-solution 处理，修复工作区由 bug-execute 处理。

## 布局

数据目录（默认 `~/.local/share/bug-workbench`）下：

```text
repositories/tutti.git            bare 缓存（cache_path）
repositories/tutti                全局分析检出（checkout_path），跟随最新 main，只读
repositories/tutti-server.git
repositories/tutti-server
repositories/tsh-websocket.git
repositories/tsh-websocket
worktrees/<仓库>/<分支>            修复时临时创建，推送后删除
```

`cache_path`、`checkout_path` 相对数据目录解析，必须位于其内。所有使用者应使用同一个数据目录；插件更新只换源码，缓存与检出保留。

## 规则

- 缓存只存 Git 对象，首次初始化，之后增量 fetch main；同一数据目录的操作通过文件锁串行。
- 全局检出是缓存的 detached worktree，同步时移动到最新 main 的 SHA；有本地改动时拒绝同步。
- 修复 worktree 从同一缓存切出，分支推送到 origin 后连同本地分支一起删除。
- 认证使用系统 Git 凭证存储，不写入插件配置。读取只需仓库读权限，修复推送需要写权限。
- 网络、权限或缓存身份错误时返回失败，已有缓存与检出保持原样。

## 预热

用户要求预热时，可调用 `$tutti-bug-workflow:bug-solution` 的代码同步完成首次初始化；初始化下载三个仓库的完整 main 历史，耗时取决于网络。
