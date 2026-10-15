# 代码缓存与检出

Setup 保存仓库配置；修复工作区由 bug-execute 处理。根因分析由 bug-analyze 在本机的固定检出里读最新代码。

## 布局

数据目录（默认 `~/.local/share/bug-workbench`）下：

```text
repositories/tutti.git            bare 缓存（cache_path）
repositories/tutti                分析用的固定检出（bug-analyze 使用），跟随最新 main，只读
repositories/tutti-server.git
repositories/tutti-server
repositories/tsh-websocket.git
repositories/tsh-websocket
worktrees/<仓库>/<分支>            修复时临时创建，推送后删除
```

`cache_path`、`checkout_path` 相对数据目录解析，必须位于其内。所有使用者应使用同一个数据目录；插件更新只换源码，缓存与检出保留。

## 规则

- 缓存只存 Git 对象，首次初始化，之后增量 fetch main；同一数据目录的操作通过文件锁串行。
- 分析用的检出跟随最新 main，有本地改动时不动它。
- 修复 worktree 从同一缓存切出，分支推送到 origin 后连同本地分支一起删除。
- 认证使用系统 Git 凭证存储，不写入插件配置。读取只需仓库读权限，修复推送需要写权限。
- 网络、权限或缓存身份错误时返回失败，已有缓存与检出保持原样。
