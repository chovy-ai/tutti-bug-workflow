# Bug 表字段与写入规则

提 Bug 写入 Bug 管理表（base `CEHMbNF8Zavq5wsAO3ecrpQ6nPc`，表「Bug 管理」，视图「新框架（一期）」），配置在数据目录 `config.json` 的 `bug_report` 段，缺省时用插件示例配置。字段通过 `bug_report.field_map` 的字段 ID 定位，改名不受影响。全部写入经 `scripts/feishu.py`，写后回读核对。

## 本 Skill 填的字段

| 配置键 | 飞书字段 | 类型 | 怎么填 |
|---|---|---|---|
| `title` | Bug 描述 | 文本 | 精简一行「类别：现象」，也是查重依据（同名视为同一条） |
| `attachments` | 截图、视频、日志 | 附件 | QA 的截图与视频、Web 现场包或诊断包、`server-logs.log`、Computer 召回包；同名同大小不重复上传 |
| `reporter` | 提交人 | 人员 | lark-cli 当前登录用户，建单时自动填 |
| `assignee` | 指派人 | 人员 | 用户指定的跟进人，`feishu.py assign` 唯一匹配后写入 |
| `status` | 状态 | 单选 | 建单时「未解决」 |
| `issue_type` | 问题类型 | 单选 | 建单时「bug」 |
| `platform` | 所属端 | 单选 | Agent 判断：`新框架一期-Mac`／`新框架一期-Windows`／`新框架一期-Web` |
| `priority` | 优先级 | 单选 | Agent 按影响面判断；P2 不进「新框架（一期）」视图 |
| `module` | 业务模块 | 单选 | Agent 从现有选项中选；没有合适的就不填 |
| `record_time` | 记录时间 | 日期 | 提问时间，按 Asia/Shanghai |
| `env_version` | 环境与版本 | 文本 | 见下 |
| `page_url` | 页面链接 | 超链接 | 出问题页面的完整 URL |
| `context` | 问题上下文 | 文本 | 见下 |

「分析根因」「修复方式」「验收标准」由 `$tutti-bug-workflow:bug-solution` 填写，「关联 PR」「验证结果」由 `$tutti-bug-workflow:bug-execute` 填写，本 Skill 不写。修复版本、自定义 tag、反馈用户、父记录、备注等也不填。

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

```
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

没有的项省略，不要编造。
