# PPE 部署

修复分支推送、PR 提交后部署到 PPE。三类部署都通过 `scripts/deploy.py` 触发对应仓库的 GitHub 工作流，等它跑完，返回 run 链接和结论（`ok`）。使用本机 `gh` 的登录态，需要对仓库有触发 workflow 的权限。

## 顺序

```
改了 tutti-server ──► server：deploy-lane.yml 部署泳道 bug-<record_id>（等待成功）
                         │
改了前端 / 需要对接泳道 ─► web：platform-web-preview.yml，branch=<tutti 分支>，server_lane=<泳道>
                         │
改了 Computer ─────────► computer：computer-artifacts-release.yml（Computer Canary）在分支上发布
```

前一步失败就不做后一步。全部部署成功后进入 [部署后自验证](verify.md)。

## 命令

| 命令 | 触发的工作流 | 返回 |
|---|---|---|
| `deploy.py lane-name --record-id REC` | — | 泳道名 `bug-<record_id 小写>`：小写字母开头，只含小写字母、数字和连字符，不以连字符结尾，最长 40 个字符 |
| `deploy.py server --branch B --lane L` | `tutti-lab/tutti-server` 的 `deploy-lane.yml`，`--ref B`，`lane=L`，`connector_authorization_enabled=false` | run 链接、结论 |
| `deploy.py web --branch B [--server-lane L]` | `tutti-lab/tutti` 的 `platform-web-preview.yml`，从 `main` 触发，`branch=B`、`server_lane=L` | run 链接、结论、预览链接 `https://tutti.sh/platform/?webBranch=B` |
| `deploy.py computer --branch B` | `tutti-lab/tutti` 的 `computer-artifacts-release.yml`，`--ref B` | run 链接、结论、canary 版本 `canary-<sha12>-<run_id>-<attempt>` |
| `deploy.py destroy-lane --lane L` | `tutti-server` 的 `destroy-lane.yml` | 只接受 `bug-` 前缀的泳道；仅在用户要求时执行 |

通用参数：`--timeout 分钟`（默认 90）、`--no-wait`（只触发）。server 可加 `--input key=value` 覆盖工作流输入。仓库、工作流名、泳道前缀、默认输入、预览链接模板在 `config.json` 的 `deploy` 段。

## 判断改了哪一端

- **server**：tutti-server 仓库有提交。
- **前端**：tutti 的 `apps/web`、以及 Web 依赖的 `packages/*` 有改动；或改了 server、需要从页面验证。只改 server 时前端分支用 `main`。
- **Computer**：tutti 的 desktopd、runtime、Computer 相关 Go 包有改动（如 `cmd/`、`runtime/`、`gopackages/`）。拿不准时按涉及处理，多部署一次只是多花时间。

## 连接器授权

每条 Bug 的泳道是新建的，没有预配 connector task-platform binding，所以部署时 `connector_authorization_enabled=false`。修复需要连接器授权才能验证时，部署后判「修复失败」，在修复进度写明需要人工预配 binding；预配完成后 RD 把方案状态改回「已批准」重试。

## 泳道回收

泳道不自动销毁，名字记在修复进度里。用户要求时用 `destroy-lane` 销毁，并在修复进度追加一行记录。
