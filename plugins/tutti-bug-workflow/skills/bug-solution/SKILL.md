---
name: bug-solution
description: RD 的根因与方案（定时）：按跟进人每小时扫描飞书 Bug 管理表中未解决、方案状态为空／未处理／已驳回的 Bug，每条 Bug 一个会话，结合 bug 单上下文、现场日志和最新代码分析根因，生成流程图与架构图 PNG，写修复方式和验收标准，再把方案状态置为待评审；也用于开启、查看、停止定时分析。
---

# 根因与方案

你面向 RD，把 `$tutti-bug-workflow:bug-investigate` 登记的 Bug 推进到「RD 已批准的方案」。修改业务代码属于 `$tutti-bug-workflow:bug-execute`。

**无状态。** 飞书 Bug 管理表里的记录是唯一事实来源，不建本地档案。脚本路径相对本 Skill 目录（`skills/bug-solution/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责。

**不改状态。** 「状态」「修复版本」「指派人」「驳回意见」由人工维护；「方案状态」只由本 Skill 从空／未处理／已驳回改成「待评审」，「已批准」「已驳回」由 RD 在飞书里选。本 Skill 只写下表字段，经 `scripts/feishu.py`，写后回读核对。字段细节见 [字段规则](references/fields.md)。

| 字段 | 内容 | 模板 |
|---|---|---|
| 分析根因 | 开头三段：根因（两三句大白话）、复现路径、预期工作流程（标出实际偏离的一步）；之后是时间线、证据、代码位置、影响范围、待确认 | [root-cause.md](assets/root-cause.md) |
| 根因图 | 流程图、架构图 PNG | [diagrams.md](assets/diagrams.md) |
| 修复方式 | 根本方案与兼容方案、取舍、推荐方案、修改范围 | [plan.md](assets/plan.md) |
| 方案状态 | 全部写完后置为「待评审」 | — |
| 验收标准 | 环境、修复前复现、验收用例、回归、通过标准 | [acceptance.md](assets/acceptance.md) |

按用户的话选一节：

- 「给张三开定时分析」「只分析 P1 以上」「停掉定时任务」 → **定时任务管理**
- 开场提示写明「定时模式」、带运行目录（由 `scripts/scan.py` 发起） → **定时模式**

方案状态的流转：

| 方案状态 | 谁改 | 定时任务 |
|---|---|---|
| 空／未处理 | — | 分析，写完置「待评审」 |
| 待评审 | 定时任务 | 不处理，等 RD |
| 已批准 | RD | 不处理；可以交给 `$tutti-bug-workflow:bug-execute` 修复 |
| 已驳回 | RD，并在「驳回意见」写原因 | 结合驳回意见和上一版重新分析，覆盖后置「待评审」 |

RD 也可以直接在飞书里改根因、方案、验收后再选「已批准」。

## 定时任务管理

在本机用 launchd 每小时跑一轮，每个跟进人一个任务。详见 [定时任务](references/schedule.md)。

```sh
python3 scripts/schedule.py install --assignee "张三" --min-priority P1   # 跟进人缺省为当前登录用户
python3 scripts/schedule.py list
python3 scripts/schedule.py run-now --assignee "张三"
python3 scripts/schedule.py uninstall --assignee "张三"
```

- 跟进人按通讯录唯一匹配；同名多人或查不到时返回候选，请用户确认后重试。
- `--min-priority` 只分析该优先级及以上（P00 > P0 > P1 > P2 > P3），用户没说就不加。
- 开启前先用 `python3 scripts/feishu.py scan --assignee "张三" --min-priority P1` 告诉用户当前待分析多少条；用户想马上看效果时加 `--run-now`。
- 每轮：列出该跟进人「未解决」且方案状态为空／未处理／已驳回的 Bug → 同步代码 → 逐条各起一个 `codex exec` 会话（本机运行，不进 sandbox），全部处理完为止。上一轮没跑完时下一轮跳过。

## 定时模式

无人值守：**不提问、不等待**，每一步都自己做完。当前目录是运行目录：

| 文件 | 内容 |
|---|---|
| `context.md` | 这条 Bug 记录的全部字段：Bug 描述、问题上下文（期望／实际／复现步骤／发生时间／关联 ID）、环境与版本、页面链接、优先级、提交人、记录时间、方案状态；被驳回时还有「驳回意见」和上一版根因、方案、验收 |
| `attachments/` | 记录上的全部附件：截图、视频、`web-logs.log` 或诊断包、`server-logs.log`、Computer 召回包 |
| `code.json` | 已同步到最新 main 的全局代码检出路径与 SHA |

1. **吃透 bug 单。** 方案状态是「已驳回」时，先读「驳回意见」和上一版内容，这一版要逐条回应驳回意见（在根因或方案里写明怎么处理的）。完整读 `context.md`；截图逐张看（开场已附上），压缩包解开读；把期望、实际、复现步骤、发生时间、关联 ID（账号、房间、Computer、Agent、request id）列出来，作为后面检索日志与代码的线索。
2. **还原现场。** 用发生时间和关联 ID 在 Web／Server／Computer 日志里找到出错的那几条，排出时间线；日志之间用 request id、房间、Computer ID 对上。
3. **定位代码。** 在 `code.json` 的检出里（只读，见 [代码检出](references/code.md)）找到对应实现，解释日志为什么会这样。「环境与版本」里的线上版本和 main 不同时，用 `git log <版本>..<sha>` 核实差异是否影响结论。
4. **写根因**：按 [根因模板](assets/root-cause.md)，开头固定三段，RD 只看这三段就能明白：
   - **根因**：两三句大白话、150 字以内，说清哪个环节在什么条件下做错了什么、导致用户看到什么；不堆术语、不贴 request id。
   - **复现路径**：前置条件和操作步骤，到出现问题的那一步。
   - **预期工作流程**：正常应该怎么走（每一步是哪一端做什么），并指出实际在哪一步偏离。
   之后才是细节：时间线、证据、代码位置、影响范围、待确认。细节里因果链每一环要么有日志或代码作证，要么标成假设；现场不够的写进「待确认」，不中断。最新 main 已修复的，根因照写，并在第一段末尾注明「最新 main 已由 <PR/提交> 修复」。
5. **画图**：按 [图规范](assets/diagrams.md) 画两张，目标是 RD 扫一眼就懂谁做了什么、哪一步出错、应该怎样：
   - `flow.mmd`：**时序图**，按端分泳道，和「预期工作流程」一一对应；出错那段红底标「❌ 根因」，预期那段绿底标「✅ 预期」。
   - `arch.mmd`：**一行从左到右的链路**，颜色区分端，问题组件标红，旁边挂黄色说明；不用分组、不画回头线。
   - 文字用大白话，不写类名、函数名、错误码常量；流程不超过 10 步，架构不超过 8 个节点。
   ```sh
   python3 scripts/render.py --input flow.mmd --input arch.mmd
   ```
   渲染后打开 PNG 自查（文字重叠、连线交叉、红色位置），不清楚就改源码重渲染。PNG 改名为 `flow-<record_id>-<yyyymmddHHMM>.png`、`arch-<record_id>-<yyyymmddHHMM>.png`。
6. **写方案与验收**：按 [方案模板](assets/plan.md) 和 [验收模板](assets/acceptance.md)；tsh-websocket 是很少改动的基础设施，根因确实在 ws 时才把它列进修改范围（修复时会多一步 ws 泳道部署）；方案里的 Mermaid 源码与 PNG 一致。
7. **写回**，每次写入都带 `--if-open`：方案状态已被 RD 改成「待评审」「已批准」时返回退出码 3，立即结束本会话，不再写任何内容：
   ```sh
   python3 scripts/feishu.py write --record-id REC --if-open \
     --set root_cause=@root-cause.md --set solution=@plan.md --set acceptance=@acceptance.md
   python3 scripts/feishu.py attach --record-id REC --file flow-REC-….png --file arch-REC-….png
   python3 scripts/feishu.py set-plan-status --record-id REC --value 待评审
   ```
   三段整体覆盖上一版；根因图新增一组，旧图保留。`set-plan-status` 只能置「待评审」，且要求三段都已写入。
8. **收尾**：最后一条消息写一行结论和写入结果（根因、方案、两张图、方案状态各自成功／跳过／失败），供运行日志查看。
