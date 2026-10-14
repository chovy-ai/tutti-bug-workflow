---
name: bug-execute
description: 修复已批准的 Bug（定时）：按跟进人每小时扫描飞书 Bug 管理表中方案状态为「已批准」的 Bug，每条 Bug 一个会话，从最新 main 切分支修复、提 PR 到 main，部署 PPE（server 泳道 → ws 泳道 → 前端预览，涉及 Computer 发分支 canary），按验收标准验证，进度和结果全部写回 bug 单；也用于开启、查看、停止定时修复，以及手动销毁某条 Bug 的 PPE 泳道。
---

# 修复与部署

你负责把 RD 已批准的方案落成代码，部署到 PPE 并验证。`$tutti-bug-workflow:bug-solution` 暂时屏蔽，分析根因、修复方式、验收标准由 RD 直接填在 bug 单上，方案状态改成「已批准」后由本 Skill 接手。

**无状态。** 飞书 Bug 管理表里的记录是唯一事实来源，不建本地档案。脚本路径相对本 Skill 目录（`skills/bug-execute/`），都输出一段 JSON。工具安装与认证由 `$tutti-bug-workflow:bug-setup` 负责。

**进度都在 bug 单上。** 字段细节见 [字段规则](references/fields.md)。

**修复部署后，体验环境必须挂在 bug 单上。** 只要有任何一端部署成功，不论最后是「已部署待验收」还是「修复失败」（例如验收用例没跑完、连接器授权缺失），「访问环境」里都要有一个点开就能体验修复的链接：前端预览链接（指向这条 Bug 的 Server 泳道）；只改了 Computer 时是 canary 发布页。这一列是链接样式，**只放一个裸链接**，不加「前端预览：」之类的前缀和说明，否则点不开。泳道、canary 版本写在修复进度和验证结果里。RD 和 QA 靠它去体验修复，漏填等于没交付。

| 字段 | 本 Skill 怎么写 |
|---|---|
| 方案状态 | 已批准 → 修复中（定时任务认领）→ 已部署待验收／修复失败；`set-plan-status` 只允许这几步 |
| 修复进度 | 每一步追加一行带时间的记录：分支、PR、泳道与部署 run、预览链接、canary 版本、失败原因 |
| 访问环境 | 一个可点击的体验链接（前端预览，只改 Computer 时为 canary 发布页）；`deploy.py --record-id` 部署成功后自动回填，为空时不能置「已部署待验收」 |
| 关联 PR | `add-pr`，每行一个 |
| 一句话解释原因 | 修复完成后根据 PR 的实际改动写**一句大白话**，说清 Bug 为什么会出现；为空时不能置「已部署待验收」 |
| 验证结果 | 按 [验证模板](assets/verification.md) 写 |
| 修复截图 | 部署 PPE 后自验证的截图，涉及 UI 的用例必须有 |

分析根因、修复方式、验收标准、状态只读；「状态」由人工流转。

按用户的话选一节：

- 「给张三开定时修复」「只修 P1 以上」「停掉定时修复」「销毁这条 bug 的泳道」 → **定时任务管理**
- 开场提示写明「定时模式」、带运行目录（由 `scripts/scan.py` 发起） → **定时模式**

## 定时任务管理

本机 launchd 每小时跑一轮，每个跟进人一个任务。详见 [定时任务](references/schedule.md)。

```sh
python3 scripts/feishu.py scan --assignee "张三" --min-priority P1        # 先告诉用户有几条已批准待修
python3 scripts/schedule.py install --assignee "张三" --min-priority P1   # 跟进人缺省为当前登录用户
python3 scripts/schedule.py list
python3 scripts/schedule.py run-now --assignee "张三"
python3 scripts/schedule.py uninstall --assignee "张三"
```

- 跟进人按通讯录唯一匹配；同名多人或查不到时返回候选，请用户确认。`--min-priority` 用户没说就不加。
- 每轮：上一轮遗留的「修复中」标为修复失败 → 列出「已批准」的 Bug → 逐条置「修复中」并各起一个 `codex exec` 会话（本机运行，不进 sandbox），全部处理完为止。
- 修复失败的 Bug，RD 看过「修复进度」处理后把方案状态改回「已批准」，下一轮会在原分支上继续。

泳道不自动销毁。用户要求销毁某条 Bug 的泳道时：

```sh
python3 scripts/deploy.py lane-name --record-id REC
python3 scripts/deploy.py destroy-lane --lane ppe-bug-rec…                      # server
python3 scripts/deploy.py destroy-lane --lane ppe-bug-rec… --service websocket  # 部署过 ws 时
python3 scripts/feishu.py progress --record-id REC --message "已销毁 PPE 泳道 ppe-bug-rec…：<run 链接>"
```

## 定时模式

无人值守：**不提问、不等待**。当前目录是运行目录：

| 文件 | 内容 |
|---|---|
| `context.md` | 已批准的分析根因、修复方式、验收标准，以及问题上下文、环境与版本、页面链接、已有的关联 PR、修复进度 |
| `attachments/`、`diagrams/` | 现场附件；根因流程图与架构图 |
| `fix.json` | 本条 Bug 固定的分支名 `codex/bug-<record_id>` 和泳道名 `ppe-bug-<record_id>` |

**每完成一步立刻写进度**：`python3 scripts/feishu.py progress --record-id REC --message "…"`。**任何一步失败**：写清卡在哪一步、错误信息和链接，然后

```sh
python3 scripts/feishu.py set-plan-status --record-id REC --value 修复失败 --note "<哪一步、原因>"
```

结束会话，不再继续后面的步骤。已经部署成功的话，访问环境照样要在 bug 单上（deploy.py 会自动写；置失败前 `feishu.py read --record-id REC --field environment` 确认一眼）。

1. **读懂方案。** 读 `context.md` 和根因图（有的话）；修复进度里有上一次的记录时，从失败的那一步接着做。确认修复要动哪些仓库：tutti（Web、Computer）、tutti-server（Server）、tsh-websocket（WebSocket，基础设施，方案没要求就不改）。
2. **切分支。** 每个要改的仓库：
   ```sh
   python3 scripts/repos.py start --repo tutti --branch codex/bug-<record_id>
   ```
   返回 `resumed: true` 表示接着上一次的分支；`behind_main` 大于 0 时先 `git rebase origin/main`（冲突解决不了就判失败）。详见 [修复工作区](references/code.md)。
3. **修复。** 读 worktree 里的 AGENTS.md 和开发说明，按方案范围修改，保持现有架构与风格；补测试，跑相关测试、类型检查、lint，直到通过。方案在最新 main 上已不成立、或修复必须超出方案范围时判失败，写明原因交还 RD。
4. **提交、推送、提 PR。**
   ```sh
   git -C <worktree> add -A && git -C <worktree> commit -m "fix: <摘要>（bug <record_id>）"
   python3 scripts/repos.py finish --path <worktree>
   gh pr create -R tutti-lab/<repo> --base main --head codex/bug-<record_id> --title "fix: …" --body "…"
   python3 scripts/feishu.py add-pr --record-id REC --url <PR 链接>
   ```
   分支已有打开的 PR（`gh pr view -R … codex/bug-<record_id>`）就复用，不重复创建。PR 描述写 bug 记录链接、根因一句话、改动、测试结果、PPE 部署信息（部署后用 `gh pr comment` 补上）。
5. **部署 PPE**，顺序固定，详见 [PPE 部署](references/deploy.md)。**每条 deploy 命令都带 `--record-id REC`**：成功后脚本把前端预览链接（只改 Computer 时为 canary 发布页）回填到「访问环境」，并把泳道／canary 版本和 run 链接写进修复进度；返回 `record_error` 时用 `feishu.py environment --record-id REC --url <链接>` 补写。
   - 改了 tutti-server：`python3 scripts/deploy.py server --record-id REC --branch codex/bug-<record_id> --lane <fix.json 的泳道>`，等它成功。
   - 改了 tsh-websocket（基础设施，很少改动；只在方案明确要求时修改，没改就跳过这一步）：`python3 scripts/deploy.py websocket --record-id REC --branch codex/bug-<record_id> --lane <同一个泳道>`。新泳道缺 WebSocket V2 基础设施会失败（看 `failed_log_tail` 和 `hint`）：其他端照常部署，最后判失败，写明需要人工先建 ws 基础设施。
   - 改了前端（或改了 server，前端需要对接这个泳道）：`python3 scripts/deploy.py web --record-id REC --branch <tutti 分支> --server-lane <泳道>`。只改了 server 时，用 `main` 作为前端分支部署预览并指向泳道。
   - 改了 Computer（desktopd、runtime 等）：`python3 scripts/deploy.py computer --record-id REC --branch codex/bug-<record_id>`，记下 canary 版本。
   - 自验证时如果用的是更具体的页面（例如带 `webBranch` 的房间页），可以用 `feishu.py environment --record-id REC --url <该链接>` 换成它，方便直接看到问题现场。
   - 泳道部署时关闭了连接器授权。修复依赖连接器授权才能验证（授权、连接器相关的 Bug）时，PR 照提、部署照做，然后判失败，说明「新泳道 bug-… 需要人工预配 connector task-platform binding 后重试」。
6. **自验证。** 部署成功后自己按「验收标准」逐条验证，完整流程见 [部署后自验证](references/verify.md)：
   - 用 `chrome-devtools` MCP 连接本机 Chrome（用它的 tutti.sh 登录态），`new_page` 打开预览链接，只操作自己开的标签页，结束后关掉。
   - **涉及 UI 的改动，每条用例都要截图**：到断言状态时 `take_screenshot` 存为 `fix-<record_id>-<用例编号>-<yyyymmddHHMM>.png`，然后上传到「修复截图」：
     ```sh
     python3 scripts/feishu.py attach --record-id REC --file fix-REC-1-….png --file fix-REC-2-….png
     ```
   - Computer 的修复写明 canary 版本，能在 canary Computer 上验证的就验证，不能的记 `not_run` 并写原因。
   - 任何必需用例失败，或涉及 UI 却没能截图（Chrome 不可用、未登录）→ 判失败。
7. **回填与收尾。**
   先写「一句话解释原因」：`gh pr diff` 看这次 PR 实际改了什么，用一句话告诉 QA 和产品这个 Bug 为什么会出现。
   - 讲原因，不讲改法；说用户看得到的现象和背后的那一步出错，不用类名、函数名、接口名、错误码；单行、不超过 80 字，最好 50 字以内。
   - 以 PR 为准：实际修的和方案里的根因不一样时，按 PR 写。
   - 例：「切换房间时顶部标题没跟着刷新，一直显示上一个房间的名字」「服务端只认公开回复，把话题里的悄悄话当成非法消息拒掉了」。
   ```sh
   python3 scripts/feishu.py write --record-id REC --set "cause=<一句话原因>"
   python3 scripts/feishu.py write --record-id REC --set verification=@verification.md
   python3 scripts/feishu.py set-plan-status --record-id REC --value 已部署待验收 --note "预览 <链接>，泳道 <泳道>"
   ```
   置状态前先 `feishu.py read --record-id REC --field environment`，确认「访问环境」是能点开的体验链接，缺了用 `feishu.py environment --url` 补上。
   最后一条消息写一行结论（一句话解释原因、PR、访问环境、验证、方案状态），供运行日志查看。用户问起时，直接给出这个可点击的链接。
