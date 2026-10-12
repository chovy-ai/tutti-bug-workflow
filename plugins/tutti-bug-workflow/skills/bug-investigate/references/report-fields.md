# Bug 表字段与写入规则

提 Bug 写入 Bug 管理表（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表「Bug 管理」，视图「新框架（一期）」），配置在数据目录 `config.json` 的 `bug_report` 段，缺省时用插件示例配置。字段通过 `bug_report.field_map` 的字段 ID 定位，改名不受影响。全部写入经 `scripts/feishu.py`，写后回读核对。

## 本 Skill 填的字段

| 配置键 | 飞书字段 | 类型 | 怎么填 |
|---|---|---|---|
| `title` | Bug 描述 | 文本 | 一行「类别：现象（触发条件／关键对照）」，见下；也是查重依据（同名视为同一条） |
| `attachments` | 截图、视频、日志 | 附件 | QA 的截图与视频、Web 现场包或诊断包、`server-logs.log`、Computer 召回包；同名同大小不重复上传 |
| `reporter` | 提交人 | 人员 | lark-cli 当前登录用户，建单时自动填 |
| `assignee` | 指派人 | 人员 | 用户指定的跟进人，`feishu.py assign` 唯一匹配后写入 |
| `status` | 状态 | 单选 | 建单时「未解决」 |
| `issue_type` | 问题类型 | 单选 | 建单时「bug」 |
| `platform` | 所属端 | 单选 | Agent 判断：`新框架一期-Mac`／`新框架一期-Windows`／`新框架一期-Web` |
| `priority` | 优先级 | 单选 | QA 给了就照填；否则按定义判断：P0 严重阻塞，P1 明显 Bug，P2 非核心 Bug；拿不准问 QA。P00／P3 只在 QA 明确说时用；P2 不进「新框架（一期）」视图 |
| `module` | 业务模块 | 单选 | 只能从 `feishu.py options --field module` 返回的现有模块中选一个，不自创；对不上时问 QA。配置 `bug_report.retired_options.module` 里是历史上被随手加的非正式选项，列表里不显示，写入时拒绝 |
| `record_time` | 记录时间 | 日期 | 提问时间，按 Asia/Shanghai |
| `env_version` | 环境与版本 | 文本 | 见下 |
| `page_url` | 页面链接 | 超链接 | 出问题页面的完整 URL |
| `context` | 问题上下文 | 文本 | 见下 |

「分析根因」「修复方式」「验收标准」由 `$tutti-bug-workflow:bug-solution` 填写，「关联 PR」「验证结果」由 `$tutti-bug-workflow:bug-execute` 填写，本 Skill 不写。修复版本、自定义 tag、反馈用户、父记录、备注等也不填。

## Bug 描述

RD 在列表里只看得到这一行，要让人不点开也知道「什么东西、在什么条件下、怎么坏了」：

- 格式：`类别：现象（触发条件／关键对照）`，40–80 字，一行。
- 现象写用户可见的结果和关键报错原文的要点，不写「异常」「有问题」这类空话。
- 括号里写区分条件：只在某种操作、设置、环境下出现，或与正常情况的关键差异。
- 只写事实，不写根因推测。

| 太简单 | 合适 |
|---|---|
| 任务：执行失败 | 任务：Claude Agent 执行任务报认证失败（模型 agnes-2.5-flash；同 Agent 同 Computer 普通会话 native/default 正常） |
| 房间：发消息失败 | 房间：本地房间 Codex 会话启动失败「cwd materialize failed」（仅本地房间，云端房间正常） |

建单时（第 2 步）还没有日志，先按用户描述写；采集完成后（第 4 步）如果确认了新的触发条件或对照，用 `feishu.py write --set title=…` 改成上面的样子。

## 环境与版本

```
环境：PPE（lane-ppe-cloud-0928）
页面域名：ppe-cloud.tutti.sh
tutti-server：<service.version>
Computer：<computerVersion>（macOS arm64）
Web：<页面版本，可从页面日志或资源路径取得>
浏览器：<UA>
```

环境来自页面域名与 Server 日志的 namespace，两者不一致时都写上。

## 问题上下文

按下面的顺序写，**最重要的放最前面**：

```
概要
<2–4 句：什么坏了、在什么条件下、用户看到的报错原文、和正常情况的关键差异、影响范围>

现场核对（事实记录，不是根因结论）
- <对照>：失败的 <任务／会话 A> 用 <设置 X>；成功的 <会话 B> 用 <设置 Y>；两者 <相同的部分：同一 Agent、同一 Computer……>
- <日志事实>：<时间> <来源：Web／Server／Computer 日志> <报错原文或关键字段>（request id／task id）
- <请求失败>：<时间> <method 路径> → <状态码>（request id）；页面失败但没到服务端的请求单独列出

期望：……
实际：……
复现步骤：1. …… 2. ……
频率：必现／偶现（约 x 次中 y 次）
发生时间：2026-10-10 17:48（Asia/Shanghai）
操作账号：<名称>（<userId>）

关联 ID
账号：<userId>
房间：<roomId>
页面会话：<web-diagnostics:uuid>
Computer：<computerId>（<名称>）
Agent：<agentTargetId>
request id：<出错或关键的几条>
召回任务：<taskId>
```

规则：

- **概要**和**现场核对**写给 RD 第一眼看。采集中核对过的每一条事实——成功／失败的对照、设置或版本差异、报错原文、服务端失败请求、日志里的异常——都写进「现场核对」，带上来源和时间，**不要塞进「关联 ID」**。
- **关联 ID** 只放 ID，不写说明文字。
- 在回复里告诉用户的每一条发现，都必须能在「概要」或「现场核对」里找到；回复里说「已写入 Bug 单」之前先回读确认。
- 只记录核对过的事实，标注来源；推测写成「待确认：……」，不写根因结论（根因由 bug-solution 分析）。
- 没有的项省略，不要编造。
