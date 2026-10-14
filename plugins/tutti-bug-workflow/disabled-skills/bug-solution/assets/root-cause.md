根因：<两三句大白话，150 字以内：哪个环节、在什么条件下、做错了什么，导致用户看到什么。不堆术语、不贴 ID，不懂代码的人也能看懂>

复现路径：
1. <账号 / 环境 / 前置条件>
2. <操作步骤>
3. <在哪一步出现问题，看到的现象>

预期工作流程：
1. <正常情况下这一流程应该怎么走，每一步由谁（Web／Server／WebSocket／Computer）做什么>
2. ……
实际在第 <N> 步偏离：<偏离点，和根因对应>

——以下为细节——

时间线（Asia/Shanghai）：
- <HH:MM:SS> <来源：Web／Server／Computer> <关键事件，带 request id 等关联 ID>

证据：
- <日志：附件名、时间、关联 ID、关键内容>
- <代码：仓库@sha 路径:行号，说明这段代码做了什么>

代码位置：
- tutti@<sha> <path>:<line>
- tutti-server@<sha> <path>:<line>
- tsh-websocket@<sha> <path>:<line>

影响范围：<哪些端、场景、用户会遇到；是否影响数据>

待确认：
- <尚未证实的假设，以及怎么验证>

分析来源：定时分析，<yyyy-mm-dd HH:MM>，<运行目录>，tutti@<sha>，tutti-server@<sha>，tsh-websocket@<sha>
