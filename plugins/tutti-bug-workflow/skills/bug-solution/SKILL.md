---
name: bug-solution
description: RD 对一条已登记的 Bug 做根因分析和方案设计：读取飞书 Bug 管理表的记录与现场日志，在全局代码检出上定位根因，给出根本方案、兼容方案和设计图，与 RD 协商修复方式和验收标准，并在 RD 批准后把批准记录写回同一条记录。
---

# 根因与方案

你面向 RD，把 `$tutti-bug-workflow:bug-investigate` 登记的一条 Bug 推进到「RD 已批准的方案」：定位根因、设计方案、写好验收标准，拿到 RD 的真实批准。修改业务代码属于 `$tutti-bug-workflow:bug-execute`。

**无状态。** 飞书 Bug 管理表里的记录是唯一事实来源，不建本地档案。`record_id` 记在会话上下文里；日志等下载到会话临时目录（下称 `$TMP`），用完即弃。脚本路径相对本 Skill 目录（`skills/bug-solution/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责。

**不改状态。** 「状态」「修复版本」等流转字段由人工操作，本 Skill 只写下表三个字段，写入经 `scripts/feishu.py`，写后回读核对。字段细节见 [字段规则](references/fields.md)。

| 字段 | 内容 | 模板 |
|---|---|---|
| 分析根因 | 结论、因果链、证据、代码位置、影响范围、待确认 | [root-cause.md](assets/root-cause.md) |
| 修复方式 | 根本方案与兼容方案、取舍、选定方案、修改范围、设计图；末尾的【RD 批准】由脚本写 | [plan.md](assets/plan.md) |
| 验收标准 | 环境、修复前复现、验收用例、回归、通过标准 | [acceptance.md](assets/acceptance.md) |

## 1. 读取记录与现场

1. 用户给的是飞书链接时从中取 `record_id`（`record=` 参数，或先用 `lark-cli base +url-resolve` 解析）。
2. 读记录，下载全部附件：
   ```sh
   python3 scripts/feishu.py read --record-id REC
   python3 scripts/feishu.py download --record-id REC --output-dir $TMP/attachments
   ```
   重点看：Bug 描述、问题上下文（期望／实际／复现步骤／发生时间／关联 ID）、环境与版本、页面链接；附件里的截图视频（实际查看）、Web 日志（`web-logs.log` 或诊断包 zip）、`server-logs.log`、Computer 召回包。
3. 已有「分析根因」「修复方式」「验收标准」时在其基础上继续，人工写的内容保留。

## 2. 同步代码

根因分析在全局代码检出上进行，所有 Bug 共用，每次分析前拉到最新 main：

```sh
python3 scripts/repos.py sync
```

返回每个仓库的 `checkout`（如 `~/.local/share/bug-workbench/repositories/tutti`）和 `sha`。检出只读：只阅读、搜索、`git log`／`blame`，不在这里改代码、切分支或装依赖。需要跑最小复现时复制到 `$TMP`。详见 [代码检出](references/code.md)。

「环境与版本」里的线上版本和 main 不一致时，用 `git log <版本>..<sha>` 核实差异是否影响根因，写进证据。

## 3. 定位根因

1. 从现场出发：按发生时间和关联 ID（request id、房间、Computer、Agent）在 Web／Server／Computer 日志里找到出错的那几条，串起时间线。
2. 回到代码：找到对应实现，解释日志为什么会这样，形成因果链。每个环节要么有日志或代码作证，要么标成假设并写出怎么验证。
3. 现场缺口（日志没覆盖、复现条件不清）列进「待确认」；需要 QA 补现场时，在回复里说清要什么，补充后再次调用本 Skill。
4. 按 [根因模板](assets/root-cause.md) 写入：
   ```sh
   python3 scripts/feishu.py write --record-id REC --set root_cause=@$TMP/root-cause.md
   ```

## 4. 设计方案与验收

1. 给出**根本方案**和**兼容方案**，比较覆盖范围、架构影响、兼容性、改动成本、回归风险和回滚方式；两者相同时说明原因。
2. 写清要改的模块、接口、状态处理，附 Mermaid 工作流程图和架构图，标出问题点和改动位置。
3. 写验收标准：修复前复现、修复后期望、执行环境与版本读取方式、正向／边界／回归用例、证据要求和通过标准。验收要能被 `bug-execute` 逐条执行。
4. 写入：
   ```sh
   python3 scripts/feishu.py write --record-id REC --set solution=@$TMP/plan.md --set acceptance=@$TMP/acceptance.md
   ```

## 5. 与 RD 协商并记录批准

1. 把根因、方案、验收的要点和飞书记录链接发给 RD，按反馈修改并重新写入。
2. RD 明确同意某个方案后记录批准，批准人必须是 RD 本人，原话照录：
   ```sh
   python3 scripts/feishu.py approve --record-id REC --approver "张三" --quote "可以，按根本方案修" --source "当前对话"
   ```
   脚本在「修复方式」末尾写入【RD 批准】：批准人、时间、原话、来源，以及当前根因、方案和验收的摘要。同名多人或查不到时返回候选，请用户确认后重试。
3. 批准只能来自 RD 的真实表态；没有明确同意就保持待批准，不替 RD 批准。
4. 批准后又改了根因、方案或验收中的任何一项，`write` 会清除批准（返回 `approval_cleared: true`），需要 RD 重新批准。

## 6. 回复

回复：飞书记录链接、根因结论、选定方案、验收要点、批准情况（已批准／待批准及缺什么）。已批准时提示可以用 `$tutti-bug-workflow:bug-execute` 修复。
