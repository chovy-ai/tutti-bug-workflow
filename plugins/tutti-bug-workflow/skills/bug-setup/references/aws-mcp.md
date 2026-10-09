# AWS MCP 显式兼容接入

当前 setup 默认使用 [AWS CLI](aws-cli.md)，不自动注册 AWS MCP。仅在用户明确要求恢复 MCP 时采用以下兼容流程，通过 Codex OAuth 直接连接。接入方式已按 [AWS OAuth 文档](https://docs.aws.amazon.com/agent-toolkit/latest/userguide/oauth-authentication.html)和 [OpenAI Docs](https://developers.openai.com/codex/mcp)核实。

## 自动注册

```sh
python3 PLUGIN_ROOT/scripts/workbench.py init
python3 PLUGIN_ROOT/scripts/workbench.py setup-aws-mcp
```

将 `PLUGIN_ROOT` 替换为当前插件目录。显式 MCP 操作注册 `tutti-aws`，使用 Codex 原生 MCP 配置，等效入口为：

```sh
codex mcp add tutti-aws --url 'https://aws-mcp.us-east-1.api.aws/mcp?oauth=initialize'
```

注册到当前 Codex 用户；其他会话可以复用，插件卸载不会自动移除服务。安装缓存保持只读，AWS 服务不再重复加入插件 `mcp_servers` 或 `mcp.json`。配置确认后保存数据目录 `connections/aws-mcp.json`，记录注册、认证与实际调用各自状态，不保存 token。

再次显式执行 MCP 配置时复用相同远程连接。旧版插件创建的 SigV4 代理，只有存在 setup 记录且实际启动配置未被修改时才迁移为 OAuth。同名的其他配置保留并报告冲突，其他 MCP、表格、仓库和 Computer 路径保持原值。

部分 Codex 版本注册时会立即尝试 OAuth。浏览器授权失败或超时后，脚本重新检查宿主配置：服务存在则报告已注册但待登录；服务未确认则报告失败。不会把登录失败等同于注册失败，也不会把已注册等同于已连接。

## 首次授权和续期

只有用户要求 MCP 授权时，才使用宿主 OAuth 登录流程；认证待完成不要求立即登录：

```sh
codex mcp login tutti-aws
```

由用户在 AWS 登录页面选择实际账号并授权，插件不能替用户完成 MFA 或同意授权。凭证由 Codex 的 MCP 认证存储管理；不要把令牌写入插件、表格或工作台配置。已保存 OAuth 凭证只标记 `oauth_credentials_present`，实际只读工具调用成功后才确认连接。

AWS 当前公布的 access token 有效期为 1 小时，refresh token 最多有效 12 小时。支持刷新时可在期限内自动续期；刷新期限结束、会话撤销或权限变化后仍可能需要重新授权。OAuth 解决本地 CLI 凭证依赖，不承诺永久免登录。账号还需具备 AWS OAuth 登录权限及目标日志读取权限；权限不足交给管理员处理，setup 不修改 IAM。

首次授权后重新加载 MCP 或新开 Codex 会话，发现实际工具，先执行一次只读调用，再核对实际账号、区域和业务日志权限。文档查询成功不代表已读到业务日志；记录网络、认证和 IAM 权限问题各自的恢复条件。

## 配置和兼容方式

```json
{
  "aws_mcp": {
    "server_name": "tutti-aws",
    "auth_mode": "oauth",
    "endpoint": "https://aws-mcp.us-east-1.api.aws/mcp",
    "region": "us-east-1",
    "profile": null
  }
}
```

`endpoint` 支持官方的 `us-east-1` 和 `eu-central-1` 地址；setup 自动追加 `?oauth=initialize`，不携带密钥。`region` 保存日志查询的默认参考区域；OAuth 模式不会像旧代理那样自动注入此区域，每次实际查询需要明确传入。`profile` 仅供 SigV4 兼容方式使用，OAuth 账号由浏览器授权决定，不能根据本机 profile 推断。

显式执行 MCP 配置但缺少 `auth_mode` 时使用 `oauth`。确需本机多 profile 切换时显式设置 `auth_mode: sigv4`，继续使用固定版本官方代理和本机凭证链；该兼容方式仍可能受本机 SSO 过期影响。同名但不同认证方式的配置需核对并按已授权目标更新，不能静默切换账号。

## 日志读取范围

OAuth 直连没有旧代理的 `--read-only` 工具过滤。因此只读是本工作流的使用约束，不能声称已在 MCP 层强制限制；AWS IAM 才是云端权限边界。优先以具有所需日志读取权限的角色授权，setup 不授予或扩大权限。Bug 分析只调用查询、读取和状态检查，不执行云端资源写入。

AWS MCP 用于已确认存储在 AWS 的服务端日志。Web 仍使用 WebMCP，本地 Computer 仍读取明确的文件路径，远端 Computer 仍使用 tutti-ops / Tutti 日志召回。按实际工具 schema 核实 CloudWatch Logs 查询能力，并限定账号、区域、日志组、时间与时区、computer/session/request 标识；保存覆盖范围、分页/截断和关键证据。注册成功不代表这些日志源已接入。
