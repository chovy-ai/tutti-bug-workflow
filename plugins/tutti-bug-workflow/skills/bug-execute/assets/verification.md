【修复结果】已部署待验收／修复失败（<一句话>）

一句话原因：<这个 Bug 为什么会出现>

体验链接：<前端预览链接；只改 Computer 时为 canary 发布页；都没部署成功写「无」>

修复：
- 分支：codex/bug-<短 ID>（tutti@<sha>，tutti-server@<sha>，tsh-websocket@<sha>，没改的仓库不写）
- PR：<链接>
- 改动：<模块与实际行为变化，对应方案的哪一部分>

自动检查：
- <命令>：<结果>

PPE 部署：
- Server 泳道：ppe-bug-<短 ID>，<run 链接>，<结论>
- WebSocket 泳道：ppe-bug-<短 ID>，<run 链接>，<结论>
- 前端预览：<预览链接>，<run 链接>，<结论>
- Computer canary：<版本>，<run 链接>，<结论>
（没涉及的一端写「未涉及」）

自验证（本机 Chrome，预览链接 <链接>；截图在 ~/.local/share/bug-workbench/bug-fixes/<taskId>/）：
1. <用例名>：passed／failed／not_run；<实际结果>；截图：fix-<短 ID>-1-<时间>.png
2. ……
修复前对照：<before- 截图文件名，或「未截」>

未覆盖与风险：<未执行的用例及原因、连接器授权等限制、后续动作>
失败时：<卡在哪一步、错误信息、run／日志链接；成功就删掉这一行>
