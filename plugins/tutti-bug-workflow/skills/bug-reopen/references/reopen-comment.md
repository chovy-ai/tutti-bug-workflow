# 打回评论与附件

验收不通过时，在原 Task 下发一条**顶层评论**，把这一轮验收的表现和现场带上，再把状态改回 `todo`。不新建 Task，也不改原来的标题、描述和附件。

## 为什么用评论，不用 `task edit`

- 附件嵌在描述里，`task edit` 带描述就是整段替换：没有再次带上的文件会从 Task 上消失。原来提 Bug 时的截图和日志不一定还在这台机器上，CLI 也不能把附件下载回来，重写描述会丢掉第一轮的现场。
- 评论是追加的：每一轮验收一条评论，第一轮现场留在描述里，后面每一轮按时间排在评论里，RD 能对照修复前后的差别。
- 评论自己带附件（`task comment --file`），文件只挂在这条评论上，不影响描述。

## 评论正文

写到 `$REPORT/验收不通过.txt`，纯文本，换行会保留，不渲染 Markdown；用空行分段，不用 `#`、`**`、表格。写给没看过这一轮验收的 RD：

```
验收不通过（第 <n> 轮，<验收人>）

验收版本
<PR、PPE 泳道或体验链接；生产版本；QA 没说就写「待 QA 确认」>

复现步骤
1. ……
2. ……

实际：<这一轮看到的结果；界面报错原文照抄>
期望：<QA 的期望，一般就是原 Task 的期望>
和修复前相比：<没变化／部分好了：……／出现新问题：……>
频率：必现／偶现（约 x 次中 y 次）／目前出现 1 次
验收时间：2026-10-16 15:20（北京时间）
环境：生产／PPE（<泳道>）· Mac／Windows／Web · <Agent 名称>

截图、录屏见下方附件；这一轮的日志和排查线索见附件「排查线索.txt」和各日志文件。

待 QA 确认
- <还在等 QA 回复的问题；没有就省略本段>
```

规则：

- **实际、期望照 QA 的意思写。** 可以精简措辞，不改意思，不补 QA 没说的期望。「和修复前相比」按 QA 的说法和原 Task 描述对照着写；QA 没说、对照不出来就写「待 QA 确认」。
- `<n>` 按 QA 说的轮次；不知道时省略「第 n 轮」，不猜。
- 描述里不写的东西评论里也不写：日志字段、request id、各种 ID、版本号、状态码、采集过程。它们放进 `排查线索.txt`。
- 不写根因推测，不评价修复方案；没证实的写进「待 QA 确认」或排查线索的「待确认」。

## 排查线索（附件）

写到 `$REPORT/排查线索.txt`，和提 Bug 时同一个格式，只是开头注明这是哪一轮验收：

```
排查线索（第 <n> 轮验收，现场事实，不是根因结论）

日志核对
- <时间> <来源：Web／Computer> <报错原文或关键字段>（request id）
- <时间> <method 路径> → <状态码>（request id）；旧版 Web 没有 id 的只写前面几项
- <和修复前现场的对照：同一个报错还在／报错变了／新出现的报错>
- 缺了哪一类现场、为什么（没有就省略）

关联 ID
账号：<userId>
房间：<roomId>
Task：<taskId>
会话：<sessionId>
Computer：<computerId>（<名称>）
Agent：<agentTargetId>
request id：<出错或关键的几条，RD 用它查 tutti-server 日志>
召回任务：<召回 taskId>
打回账号：<whoami 的 name（userId）>

环境与版本
环境：生产／PPE（lane-ppe-xxx）
验收版本：<PR、泳道、体验链接>
Computer：<computerVersion>（macOS arm64）
Web：<页面版本>
浏览器：<UA>
页面链接：<验收页面的完整 URL>

状态
打回前：<task show 读到的状态，如 in_review>
打回后：todo

附件
- <文件名>：<一句话说明>
```

只记录核对过的事实并标注来源；推测写成「待确认：……」。

## 评论附件

| 材料 | 上传什么 |
|---|---|
| QA 这一轮的截图、视频 | 原文件，先复制到 `$REPORT` |
| 排查线索 | `排查线索.txt` |
| Web 日志 | `merge_web_logs.py` 合并的 `web-logs.log`；或 QA 导出的 `tutti-web-diagnostics-*.zip` |
| Computer | 召回包原件（`*.tar.gz`），不拆包 |

- **限制**和 Task 附件相同：非空的普通文件，不能是目录或符号链接；同一次调用里文件名不能重复（同名的先复制改名）；一次合计不超过 500 MiB、最多 256 个；不接受 HTML、XHTML、SVG 等会在浏览器里执行的内容，需要时先打成 zip。超过 500 MiB 时优先去掉最大的召回包，在排查线索里写明本地路径。
- 不上传查询的原始结果、解包后的目录、中间文件（留在 `$REPORT`，不删除）。
- 有 Workspace 的云端房间里，文件已经在 Room 里时可以用 `--room-file /room/<路径>` 引用；本地房间只能用 `--file`。

## 发送与重试

```sh
tutti-cli task comment --room-id <roomId> --task-id <taskId> \
  --content-file <$REPORT>/验收不通过.txt \
  --file <$REPORT>/screenshot-1.png --file <$REPORT>/排查线索.txt \
  --file <$REPORT>/web/web-logs.log --file <$REPORT>/computer/<召回包>.tar.gz \
  --operation-id <comment_operation_id> --json
```

- 不带 `--agent-target-id`：这是给人看的评论，不触发 Agent。
- 回执 `status: posted` 才算发出，记下 `commentId`（等于 `--operation-id`）。
- 超时、断网、没拿到回执时，用**同一个** `--operation-id`、同一份正文和同一组文件重试一次。评论 ID 就是操作 ID，不会出现两条评论；重试返回 `COMMENT_IDEMPOTENCY_CONFLICT` 说明第一次已经发出（重新上传的附件 ID 不同），不再重发。
- 上传或参数报错时评论没有发出：按报错修正（文件名重复、空文件、超限、HTML／SVG 等）后用同一个操作 ID 重跑；修不了的文件去掉，在排查线索里写一句缺什么。

## 后到的现场

评论发出后才到的现场（召回晚完成、QA 补了诊断包或截图），用 `--reply-to <打回评论的 commentId>` 回复在同一个线程里（重新分析的 Agent 也在这个线程里），只带新文件和一句说明，不重发已经挂过的文件，不改状态。新文件同时补进 `排查线索.txt` 的本地副本，但不重新上传它。

重新分析发出时缺的正是这份现场（指令的现场线索里写了缺什么），就把这条回复直接交给同一个 Agent 和模型复核，免得它按不全的现场下结论（细则见 [补齐现场后复核](rd-reanalysis.md#补齐现场后复核)）：

```sh
tutti-cli task run --room-id <roomId> --task-id <taskId> --agent-target-id <同一个 Agent> \
  --reply-to <commentId> --model <同一个模型> --reasoning-effort high \
  --instruction-file <$REPORT>/rd-review.txt --file <新文件> --operation-id <新 UUID> --json
```

没发重新分析（QA 说不用），或补充不影响分析时，只发评论：

```sh
tutti-cli task comment --room-id <roomId> --task-id <taskId> --reply-to <commentId> \
  --content "补充第 <n> 轮验收现场：<一句话说明>" \
  --file <新文件> --operation-id <新 UUID> --json
```
