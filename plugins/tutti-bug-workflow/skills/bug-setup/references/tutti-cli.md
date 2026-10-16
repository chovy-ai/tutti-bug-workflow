# Tutti CLI（建 Room Task）的安装与登录

QA 提 Bug 用全局安装的 `tutti-cli` 以 QA 自己的 Tutti 账号在指定 Room 建 Task、编辑并上传附件；验收打回用它发评论、把 Task 改回待办。它是 npm 包 `@tutti-os/tutti-cli`（账号登录版），直接调用 Tutti 服务，不需要 Computer 或 Room Agent。Computer 自带的 Agent 版 `tutti-cli` 同名但没有 `login`，不能代替它。

## 1. 检查

```sh
python3 scripts/prepare.py check --scene investigate   # 看 tutti-cli 一项
```

等价的手动检查：

```sh
node --version                 # 需要 v24 及以上
tutti-cli --help               # 必须列出 login、whoami、room list、task create／edit／show／status，task comment 带 --file
tutti-cli whoami --json        # 返回账号即已登录
```

## 2. 安装

| 情况 | 处理 |
|---|---|
| Node.js ≥ 24，没装、不是 npm 上的最新版（`tutti-cli --version` 对比 `npm view @tutti-os/tutti-cli version`）、缺少 `room list`／`task run`、`task comment` 不支持 `--file`、没有 `task status`（0.1.3 起才有），或 PATH 里是 Agent 版 | `prepare.py fix` 自动运行 `npm install -g @tutti-os/tutti-cli@latest`，不用征求同意；npm 查不到最新版本（断网）时保留已装的版本 |
| Node.js < 24 | 转成用户项：`nvm install 24 && nvm use 24 && nvm alias default 24`（或 `brew install node`），用户回复「已完成」后再 `fix` |
| npm 全局目录没有写权限 | 改用 nvm 的 Node 再装，不用 `sudo` |
| 用 nvm 且有多个 Node 版本 | 全局包按 Node 版本分开装：确认 `nvm alias default` 指向装了 tutti-cli 的那个版本，否则新终端里找不到 |
| `tutti-cli --help` 仍没有 `login` | PATH 里有同名的 Agent 版排在前面：用 `"$(npm prefix -g)/bin/tutti-cli"` 调用，或把 npm 全局 bin 目录放到 PATH 前面 |

升级：`npm install -g @tutti-os/tutti-cli@latest`；装好后 `tutti-cli --version` 记下版本。

## 3. 登录

Agent 后台运行 `tutti-cli login`：它在本机打开 Tutti 登录页并等待（最长 5 分钟），用户在浏览器里用要建 Bug 的账号登录即可，不用回复。命令返回后运行 `tutti-cli whoami --json` 确认账号。

- 浏览器没自动打开时改用 `tutti-cli login --no-browser`，把打印的链接给用户在**本机**浏览器打开（回调只监听本机）。
- 会话保存在 `~/.tutti-cli/session.json`（目录 0700、文件 0600），只发往登录时的站点；默认 `https://tutti.sh`，`TUTTI_CLI_ORIGIN` 可切到其他环境，切换后要重新登录。
- 登录的账号必须是目标 Room 的成员；权限由服务端按成员身份判断，Setup 不试建 Task 来验证。
- 换账号：`tutti-cli logout` 后重新 `login`。

## 能力边界

有 `login`／`whoami`／`logout`、`room list [--type all|local|cloud] [--all]`、`agent list`／`agent models` 和 `task create`／`edit`／`show`／`status`／`comment`／`run`。`room list` 分页列出当前账号能访问的房间（本地／云端、ID、名称），bug-investigate 用 `--all` 读全后按 Room ID、房间名或用户名找房间；`agent list`／`agent models` 列出 Room 里的 Agent 和可选模型，`task run` 把指令作为 Task 评论交给指定 Agent 执行，bug-investigate 用它把根因分析交给 Room 里的 Agent（Codex 优先，其次 Claude Code），bug-reopen 用它（带 `--reply-to`）在打回评论的线程里交给 Agent 重新分析；`task comment --file` 把本机文件作为评论附件上传，bug-execute 用它把验证截图随修复回复发到 Task，bug-reopen 用它把这一轮验收的截图和日志随打回评论发到 Task；`task status` 以登录账号的成员权限改 Task 状态（不打断、也不启动 Agent），bug-reopen 用它把 Task 改回 `todo`。Computer 自带的 Agent 版也有 `task status`，但只能改 Agent 自己的 Task。每条 `task`、`agent` 命令显式带 `--room-id`。不能列出 Task、读评论或修改优先级；排查线索写成附件，跟进人在任务看板指派。
