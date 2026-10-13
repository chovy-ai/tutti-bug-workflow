# tutti-ops 安装与认证

远端 Computer 日志召回与会话上传都依赖 tutti-ops；本页说明安装、Token 配置与权限验证。

## 准备与发现

setup 运行 `scripts/workbench.py setup-tutti-ops --install`。已有可用命令时复用；缺少时检查 Node.js >=20、npm，并按用户指定方式安装：

```sh
npm install -g @tutti-os/tutti-ops-cli
```

辅助脚本记录实际可执行路径和包版本；全局安装目录未在 PATH 中时使用返回路径。此 npm 包没有根级 `--version` 参数，版本从对应包的 `package.json` 读取；没有版本元数据时记录 unknown，再按帮助与 schema 核对能力。此安装脚本不启动登录、不查询远端账号或日志；Agent 在全体安装阶段结束后立即进入下文的认证检查与处理。

使用具体 Bug 前发现实际命令，以下示例的 `tutti-ops` 可替换为 setup 返回的入口：

```sh
tutti-ops computer --help
tutti-ops capabilities --module computer
tutti-ops schema computer.devices.list
tutti-ops schema computer.devices.get
tutti-ops schema computer.log-recalls.list
tutti-ops schema computer.log-recalls.get
tutti-ops schema computer.log-recalls.create
tutti-ops schema computer.log-recalls.download-url
```

当前 npm 包提供上面的原子操作，不提供 `computer +collect-logs` 或 `computer +download-logs`。此前核对的 Git main `5c7111ca224e07d29fcfaa2a48ef589d0515fb35`（源码版本同为 0.1.6）包含组合工作流，但不能据此调用已安装包中不存在的命令。未来入口的能力清单实际包含组合命令时，再读取其 schema 使用；组合下载仍需核对是否只生成链接。

## 环境与认证

管理端入口为 [https://admin.tutti.sh](https://admin.tutti.sh)，用户已确认；tutti-ops 0.1.7 及以上（已核对 0.1.8）会将这个管理端地址归一化为 API origin `https://tutti.sh`，按本机 `dist/config.js` 和实际帮助核对。显式传入 `--admin-url`，复用与该 origin 匹配的 Token。其他环境使用其已确认地址和认证；CLI 请求路径已包含 `/api/desktop`，origin 保留根地址。

tutti-ops 远端访问需要从 [管理端](https://admin.tutti.sh) 取得 Token。由环境维护方准备，普通 QA 反馈按「QA 只回答现场问题、技术缺口交给维护方」的原则提出必要的现场问题。已有匹配 origin 且有效的 Token 时复用；本机调用成功说明已有 Token 可用，仍需为新使用者准备各自的认证与权限。

需要维护方获取 Token、登录或补充日志权限时，先按 [面向使用者的管理端教程](setup-user-guide.md#远端日志如何授权) 引导本人完成；下面保留执行侧认证与验证步骤。

认证准备按以下顺序进行；以下示例使用已确认的 `https://admin.tutti.sh`，切换环境时替换为对应地址：

1. **取得 Token**：环境维护方登录 [管理端](https://admin.tutti.sh)，获取具备本轮所需权限的 Token。缺少管理端账号或 Token 签发权限时记录维护侧缺口；Token 缺失或失效时由该入口补齐。具体页面和有效期按管理端实际说明核对。
2. **直接配置 Token**：安装阶段结束后运行 `python3 PLUGIN_SOURCE/skills/bug-setup/scripts/workbench.py configure-tutti-token --admin-url https://admin.tutti.sh`，在本机终端隐藏输入 Token。无需另行运行 `tutti-ops auth login`。该入口仅向校验子进程注入 `TUTTI_ADMIN_TOKEN`，移除该子进程的 `TUTTI_ADMIN_COOKIE`，通过 CLI 的只读 `auth status --metadata-only true` 验证后，原子保存到 CLI 原生的 `~/.config/tutti-ops/config.json`（POSIX 文件权限 0600），后续 tutti-ops 命令自动复用。失败保留旧配置，不回显上游原始输出。`--token-env` 可读取并保存已由宿主安全注入的 `TUTTI_ADMIN_TOKEN`，`--token-stdin` 可从安全输入通道读取；Token 不放在命令参数、聊天、插件源码或工作台报告中。已有有效且 origin 匹配的 Token 直接复用，更换环境时重新核对。
3. **验证能力**：在已授权认证检查时，运行 `tutti-ops --admin-url https://admin.tutti.sh --mode read auth status --metadata-only true` 和 `auth permissions`，仅保留非秘密身份/权限元数据，再实际查询已确认 Computer 及其日志任务。身份有效、目录可读、历史包下载和新召回各自有独立状态。Token 已导入本身不表示全部业务权限已通过。

独立安装步骤只准备 CLI；完整 Setup 或选中远端能力时，Agent 接着按 [主动补齐授权](setup-user-guide.md#主动补齐授权) 检查实际 origin 的身份和权限。缺少 Token 时立即提供管理密钥入口并准备 `configure-tutti-token` 的隐藏输入终端；本人配置后复查身份、权限和设备目录，安装完成与远端可用分别报告。

目录查询、任务查询与生成历史包链接是 read；创建召回是 write。CLI 的 `--mode` 是本地执行策略，不授予服务端权限。缺少身份、权限或路由时分别记录缺口，不能仅凭 401 判定 Token 是唯一原因。
