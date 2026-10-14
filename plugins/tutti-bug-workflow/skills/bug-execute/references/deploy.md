# PPE 部署

修复分支推送、PR 提交后部署到 PPE。三类部署都通过 `scripts/deploy.py` 触发对应仓库的 GitHub 工作流，等它跑完，返回 run 链接和结论（`ok`）。使用本机 `gh` 的登录态，需要对仓库有触发 workflow 的权限。

## 顺序

```
改了 tutti-server ──► server：tutti-server deploy-lane.yml，泳道 ppe-bug-<短 ID>（等待成功）
                         │
改了 tsh-websocket ──► websocket：tsh-websocket deploy-lane.yml，同一个泳道（新泳道需人工先建 ws 基础设施）
                         │
改了前端 / 需要对接泳道 ─► web：platform-web-preview.yml，branch=<tutti 分支>，server_lane=<泳道>
                         │
改了 Computer ─────────► computer：computer-artifacts-release.yml（Computer Canary）在分支上发布
```

前一步失败就不做后一步。全部部署成功后进入 [部署后自验证](verify.md)。

## 命令

| 命令 | 触发的工作流 | 返回 |
|---|---|---|
| `deploy.py fix-names --task-id <taskId>` | — | 分支 `codex/bug-<短 ID>` 和泳道 `ppe-bug-<短 ID>`（短 ID 是 Task ID 去掉连字符后的前 8 位）；泳道tutti-server 与 tsh-websocket 共用，两边都部署到 namespace `lane-<泳道>`，名字同时满足两边规则（`ppe-` 开头，小写字母、数字、连字符，最长 40） |
| `deploy.py server --branch B --lane L` | `tutti-lab/tutti-server` 的 `deploy-lane.yml`，`--ref B`，`lane=L`，`connector_authorization_enabled=false` | run 链接、结论 |
| `deploy.py websocket --branch B --lane L` | `tutti-lab/tsh-websocket` 的 `deploy-lane.yml`，`--ref B`，`lane=L` | run 链接、结论；失败时附 `hint` |
| `deploy.py web --branch B [--server-lane L]` | `tutti-lab/tutti` 的 `platform-web-preview.yml`，从 `main` 触发，`branch=B`、`server_lane=L` | run 链接、结论、预览链接 `https://tutti.sh/platform/?webBranch=B` |
| `deploy.py computer --branch B` | `tutti-lab/tutti` 的 `computer-artifacts-release.yml`，`--ref B` | run 链接、结论、canary 版本 `canary-<sha12>-<run_id>-<attempt>` |
| `deploy.py destroy-lane --lane L [--service server\|websocket]` | 对应仓库的 `destroy-lane.yml`（默认 server） | 只接受 `ppe-bug-` 前缀的泳道；仅在用户要求时执行 |

成功的 web 部署返回 `access_url`（前端预览链接），computer 部署返回 canary 发布页，作为 Task 回复里的体验链接。通用参数：`--timeout 分钟`（默认 90）、`--no-wait`（只触发）。失败时结果带 `failed_log_tail`（失败步骤日志的最后 60 行），写进 Task 回复前先看它判断原因。server 可加 `--input key=value` 覆盖工作流输入。仓库、工作流名、泳道前缀、默认输入、预览链接模板在 `config.json` 的 `deploy` 段。

## 判断改了哪一端

- **server**：tutti-server 仓库有提交。
- **websocket**：tsh-websocket 仓库有提交。ws 是很少改动的基础设施，只有方案明确要改 ws 时才会动它，绝大多数修复不涉及这一步。
- **前端**：tutti 的 `apps/web`、以及 Web 依赖的 `packages/*` 有改动；或改了 server、需要从页面验证。只改 server 时前端分支用 `main`。
- **Computer**：tutti 的 desktopd、runtime、Computer 相关 Go 包有改动（如 `cmd/`、`runtime/`、`gopackages/`）。拿不准时按涉及处理，多部署一次只是多花时间。

## 连接器授权

每条 Bug 的泳道是新建的，没有预配 connector task-platform binding，所以部署时 `connector_authorization_enabled=false`。修复需要连接器授权才能验证时，部署后判失败，在 Task 回复里写明需要人工预配 binding；预配完成后 RD 再让本 Skill 修复同一条 Task（接着原分支）。

## WebSocket 基础设施

只有改了 tsh-websocket 代码才部署 ws 泳道，没改就跳过。

tsh-websocket 的泳道部署要读取该泳道的 WebSocket V2 部署契约（按泳道创建的 IAM 角色、API Stage、`https://ws.tutti.sh/<泳道>` 回调）。新泳道没有这些，要先运行 `deploy-websocket-v2-infrastructure.yml`（`environment_name=<泳道>`，需要审核的 IAM 变更），这一步不自动执行。ws 部署失败、`failed_log_tail` 里是部署契约或 IAM 角色相关错误时：PR 照提，其他端照常部署，然后判失败，Task 回复写明「泳道 ppe-bug-… 需要人工先建 WebSocket V2 基础设施」；建好后 RD 再让本 Skill 修复同一条 Task。

## 泳道回收

泳道不自动销毁，名字写在 Task 回复里。用户要求时用 `destroy-lane` 销毁；部署过 ws 的泳道两边都要销毁（`--service server` 和 `--service websocket`），并在 Task 里回复一句。
