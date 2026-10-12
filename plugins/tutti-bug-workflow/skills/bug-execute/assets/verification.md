结论：通过／未通过（<一句话>）

一句话解释原因：<与「一句话解释原因」列同一句话>

修复：
- 分支：codex/bug-<record_id>（tutti@<sha>，tutti-server@<sha>，tsh-websocket@<sha>，没改的仓库不写）
- PR：<链接>
- 改动：<模块与实际行为变化，对应方案的哪一部分>

自动检查：
- <命令>：<结果>

PPE 部署：
- Server 泳道：ppe-bug-<record_id>，<run 链接>，<结论>
- WebSocket 泳道：ppe-bug-<record_id>，<run 链接>，<结论>
- 前端预览：<预览链接>，<run 链接>，<结论>
- Computer canary：<版本>，<run 链接>，<结论>
（没涉及的一端写「未涉及」）

自验证（本机 Chrome，预览链接 <链接>）：
1. <用例名>：passed／failed／not_run；<实际结果>；截图：fix-<record_id>-1-<时间>.png
2. ……
修复前对照：<before- 截图文件名，或「未截」>

未覆盖与风险：<未执行的用例及原因、连接器授权等限制、后续动作>
