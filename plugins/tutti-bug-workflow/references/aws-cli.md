# AWS CLI 安装与日志读取

默认使用 AWS CLI v2 直接读取 AWS 日志。安装脚本准备命令和配置；完整 Setup 或选中 AWS 的场景随后检查身份、处理认证缺口并验证已确认日志来源，见 [主动补齐授权](setup-user-guide.md#主动补齐授权)。MCP 仅按明确选择接入。

## setup

```sh
python3 PLUGIN_ROOT/scripts/workbench.py setup-aws-cli --install
```

将 `PLUGIN_ROOT` 替换为当前插件目录。脚本先运行 `aws --version`，复用已存在的 CLI v2；缺少 v2 时运行 AWS 官方安装器，新安装固定为已核实的 `2.34.11`。安装成功后再次核对版本，返回实际可执行文件路径。它不会升级或覆盖已有 v2，也不改写 AWS 认证配置。

也可以在配置初始化后独立安装：

```sh
python3 PLUGIN_ROOT/scripts/workbench.py install-cli --name aws
```

`aws` 依赖的 installer 为 `aws-official`；它不走 npm 安装器。旧配置通过 `setup-aws-cli` 补齐此依赖，保留其他用户设置。该安装命令不访问 AWS 业务接口，报告 `authentication: not_checked` 和 `business_logs_access: not_checked`；Agent 随后运行身份检查并接续授权流程，安装回执不能代表该能力已就绪。

旧版插件创建的 AWS MCP 在确认 CLI 可用后移除，前提是存在 setup 记录且实际连接未被修改；同名其他连接保留并报告冲突。此清理不撤销账号授权，不删除 AWS 登录缓存，不影响其他 MCP。

## 官方安装手段

安装来源及当前用户安装方式已按 [AWS 官方安装文档](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)及实际发布的安装脚本核实。

| 系统 | 插件的安装方法 | 安装位置 |
|---|---|---|
| macOS / Linux | 下载官方 `https://awscli.amazonaws.com/v2/install.sh`，核对插件保存的 SHA-256，再用 Bash 执行 `--version 2.34.11` | 数据目录 `tools/aws/data` 和 `tools/aws/bin`，使用返回的实际命令路径 |
| Windows | 下载官方 `https://awscli.amazonaws.com/v2/install.ps1`，核对 SHA-256，再用 PowerShell 执行 `-Version 2.34.11` | 当前用户的 `%LOCALAPPDATA%/Programs/Amazon/AWSCLIV2` |

macOS / Linux 通过该子进程的 `XDG_DATA_HOME`、`XDG_BIN_HOME` 指向独立工具目录；不修改 shell 配置或全局 PATH，不使用 sudo。Windows 使用官方当前用户安装方式，不请求系统级安装。后续调用使用 setup 返回的命令路径，避免 PATH 尚未刷新或发现旧版 CLI。

脚本入口的哈希对应本插件核实的官方内容；入口变更则停止执行，维护插件时重新核实并更新，不能跳过校验。macOS 安装器校验 PKG 签名，Windows 校验 MSI 签名；Linux 安装器在有 GPG 时校验签名，依赖与系统支持范围以官方安装器反馈为准。下载失败、系统不支持、安装失败或最终版本不符均不记录为安装成功。

## 配置和授权

```json
{
  "aws_cli": {
    "profile": null,
    "region": "us-east-1"
  }
}
```

`profile: null` 复用 CLI 当前凭证链，不切换账号；已有指定 profile 时填其实际名称。`region` 是查询的参考区域，每条 Bug 还需核对目标账号、环境和日志区域。旧 `aws_mcp` 中已有的 profile、region 可迁入 CLI 设置，其他旧设置保留，不用于自动注册 MCP。

完整初始化或场景选中 AWS 时检查授权：

```sh
python3 PLUGIN_ROOT/scripts/workbench.py setup-aws-cli --check-auth
```

该检查使用实际 CLI 调用 `sts get-caller-identity`，明确传入配置的区域及可选 profile；只报告认证状态，不回显账户 ARN、凭证或原始错误。检查成功仍不代表有目标日志权限。检查脚本不会自动启动登录；Agent 根据结果按下面的实际登录方式继续处理，并推进其他独立准备。

IAM Identity Center / SSO 已配置时使用 `aws sso login`，需要指定 profile 时追加 `--profile`；首次配置按 [AWS SSO 文档](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)运行 `aws configure sso`。使用控制台登录的身份时可按 [AWS 本地开发登录文档](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html)选择 `aws login`。按实际身份选择方法，不为避开过期而改写账号或凭证来源。

Setup 身份检查发现缺口时，Agent 直接发起适用登录并引导实际浏览器登录 / MFA；用户明确跳过时才延期。会话过期时保留任务进度，报告重新登录方式，完成登录后重试原来的只读查询；不承诺永久免登录。

## 日志分析

按实际 CLI 的帮助核对 CloudWatch Logs 命令和参数，先确认日志组、区域、时间与时区，再按 computer/session/request 等标识限定查询。只执行查询、读取和状态检查；记录命令、目标来源、时间覆盖、分页/截断和关键证据。安装、STS 检查、读取业务日志分别报告，空结果不能当作没有错误。

Web 仍使用 WebMCP，本地 Computer 仍读取明确文件路径，远端 Computer 仍使用 tutti-ops / Tutti 日志召回；只有确认日志存储在 AWS 后才走 AWS CLI。
