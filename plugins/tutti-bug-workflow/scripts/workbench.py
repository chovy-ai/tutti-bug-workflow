#!/usr/bin/env python3
"""Local configuration, dossier and handoff helpers; Python standard library only."""

import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from urllib.parse import urlparse
from urllib.request import urlopen

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
PACKAGE = re.compile(r"(?:@[a-z0-9_.-]+/)?[a-z0-9][a-z0-9_.-]*\Z")
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")
SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
ARTIFACTS = ("analysis.md", "plan.md", "acceptance.md")
AWS_PROXY = "mcp-proxy-for-aws-cli==1.7.0"
TUTTI_OPS_INSTALLER = {"type": "npm-global", "package": "@tutti-os/tutti-ops-cli"}
AWS_ENDPOINTS = {"https://aws-mcp.us-east-1.api.aws/mcp",
                 "https://aws-mcp.eu-central-1.api.aws/mcp"}
AWS_INSTALLERS = {
    "unix": ("https://awscli.amazonaws.com/v2/install.sh",
             "80f4b79b35bb5c427261e8e9f0fd6959ad3513a697f6e37d823959a72cb654dc"),
    "windows": ("https://awscli.amazonaws.com/v2/install.ps1",
                "b0bdaa6d6163331440b8ee8bdab03f86ed7378699214863140725be9970b8ec3"),
}


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_json(path):
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".workbench-", delete=False) as stream:
            temp = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temp.replace(path)
    finally:
        if temp and temp.exists():
            temp.unlink()


def data_root(args):
    selected = (args.data_dir or os.environ.get("BUG_WORKBENCH_DATA")
                or os.environ.get("PLUGIN_DATA")
                or str(Path.home() / ".local/share/bug-workbench"))
    path = Path(selected).expanduser().resolve()
    if path == PLUGIN_ROOT or PLUGIN_ROOT in path.parents:
        raise ValueError("Keep runtime data outside the plugin source/cache.")
    return path


def config_path(args, root):
    return Path(args.config).expanduser().resolve() if args.config else root / "config.json"


def load_config(args, root):
    value = read_json(config_path(args, root))
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported configuration schema_version.")
    dependencies = value.get("cli_dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("cli_dependencies must be a list.")
    seen = set()
    for item in dependencies:
        if (not isinstance(item, dict) or not NAME.fullmatch(str(item.get("name", "")))
                or not isinstance(item.get("command"), str) or not item["command"]):
            raise ValueError("Each CLI needs a valid name and command.")
        if item["name"] in seen:
            raise ValueError("CLI dependency names must be unique.")
        seen.add(item["name"])
    return value


def initialize(args, root):
    for name in ("bugs", "tools"):
        (root / name).mkdir(parents=True, exist_ok=True)
    target = root / "config.json"
    if target.exists():
        action = "preserved"
    else:
        source = (Path(args.config).expanduser().resolve() if args.config
                  else PLUGIN_ROOT / "config/workbench.example.json")
        write_json(target, read_json(source))
        action = "created"
    emit({"data_dir": str(root), "config": str(target), "action": action,
          "external_connections": "not_checked", "trigger": "manual"})


def tool_directory(root, name):
    path = (root / "tools" / name).resolve()
    if root not in path.parents:
        raise ValueError("Tool path escapes data directory.")
    return path


def tool_bin(prefix, command):
    return prefix / "node_modules/.bin" / (command + ".cmd" if os.name == "nt" else command)


def installed_command(root, item):
    installer = item.get("installer")
    if isinstance(installer, dict) and NAME.fullmatch(item["command"]):
        prefix = tool_directory(root, item["name"])
        receipt = prefix / "installation.json"
        if installer.get("type") == "npm-global" and receipt.is_file():
            saved = read_json(receipt)
            value = saved.get("executable")
            if (saved.get("installer") == installer and isinstance(value, str)
                    and Path(value).is_absolute() and Path(value).is_file()):
                return value
        executable = (aws_private_executable(root) if installer.get("type") == "aws-official"
                      else tool_bin(prefix, item["command"]))
        if receipt.is_file() and executable.is_file():
            if read_json(receipt).get("installer") == installer:
                return str(executable)
    return shutil.which(item["command"])


def tutti_ops_version(executable):
    resolved = Path(executable).resolve()
    manifests = [parent / "package.json" for parent in list(resolved.parents)[:4]]
    manifests.append(Path(executable).parent / "node_modules/@tutti-os/tutti-ops-cli/package.json")
    for manifest in manifests:
        if not manifest.is_file():
            continue
        try:
            package = read_json(manifest)
        except (ValueError, OSError):
            continue
        if package.get("name") == TUTTI_OPS_INSTALLER["package"] and VERSION.fullmatch(str(package.get("version", ""))):
            return {"version": package["version"], "version_source": str(manifest)}
    return {"version": "unknown", "version_source": None}


def ensure_tutti_ops(root, install=False):
    item = {"name": "tutti-ops", "command": "tutti-ops", "installer": TUTTI_OPS_INSTALLER}
    executable = installed_command(root, item)
    action = "reused"
    prefix = tool_directory(root, "tutti-ops")
    if not executable:
        if not install:
            return {"action": "installation_required", "executable": None,
                    "install_command": ["npm", "install", "-g", TUTTI_OPS_INSTALLER["package"]]}
        npm, node = shutil.which("npm"), shutil.which("node")
        if not npm or not node:
            raise ValueError("tutti-ops setup requires Node.js >=20 and npm in PATH.")
        runtime = subprocess.run([node, "--version"], capture_output=True, text=True,
                                 timeout=30, check=False)
        major = re.match(r"v?(\d+)\.", runtime.stdout.strip())
        if runtime.returncode or not major or int(major[1]) < 20:
            raise ValueError("tutti-ops setup requires Node.js >=20; npm install was not started.")
        prefix.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([npm, "install", "-g", TUTTI_OPS_INSTALLER["package"]],
                                capture_output=True, text=True, timeout=300, check=False)
        (prefix / "npm-install.stdout.log").write_text(result.stdout, encoding="utf-8")
        (prefix / "npm-install.stderr.log").write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            raise ValueError(f"Global tutti-ops installation failed; inspect {prefix / 'npm-install.stderr.log'}.")
        executable = shutil.which("tutti-ops")
        if not executable:
            location = subprocess.run([npm, "prefix", "-g"], capture_output=True, text=True,
                                      timeout=30, check=False)
            global_root = Path(location.stdout.strip())
            if location.returncode or not location.stdout.strip() or not global_root.is_absolute():
                raise ValueError("npm did not report its absolute global prefix.")
            candidate = global_root / ("tutti-ops.cmd" if os.name == "nt" else "bin/tutti-ops")
            if not candidate.is_file():
                raise ValueError("npm completed without an accessible tutti-ops executable.")
            executable = str(candidate)
        action = "installed"
    capability = subprocess.run([executable, "computer", "--help"], capture_output=True,
                                text=True, timeout=30, check=False)
    if capability.returncode:
        raise ValueError("tutti-ops computer --help failed; Computer commands are not verified.")
    version = tutti_ops_version(executable)
    write_json(prefix / "installation.json", {"installer": TUTTI_OPS_INSTALLER,
               "command": "tutti-ops", "executable": executable, **version})
    return {"action": action, "executable": executable, **version,
            "package": TUTTI_OPS_INSTALLER["package"], "computer_commands": "help_verified"}


def setup_tutti_ops(args, root):
    cfg = load_config(args, root)
    dependencies = cfg.setdefault("cli_dependencies", [])
    item = next((entry for entry in dependencies if entry["name"] == "tutti-ops"), None)
    if item is None:
        item = {"name": "tutti-ops", "command": "tutti-ops"}
        dependencies.append(item)
    if item["command"] != "tutti-ops" or item.get("installer") not in (None, TUTTI_OPS_INSTALLER):
        raise ValueError("tutti-ops setup expects its standard global npm installer; custom configuration is preserved.")
    item.update(required=True, installer=dict(TUTTI_OPS_INSTALLER))
    write_json(config_path(args, root), cfg)
    prepared = ensure_tutti_ops(root, install=args.install)
    report = {"ok": prepared["executable"] is not None, "transport": "cli", "installation": prepared,
              "authentication": "not_checked", "business_logs_access": "not_checked"}
    write_json(root / "connections/tutti-ops.json", report)
    emit(report)
    return 0 if report["ok"] else 2


def configure_tutti_token(args, root):
    """Validate a supplied token before updating the CLI's private credential file."""
    cfg = load_config(args, root)
    item = next((entry for entry in cfg["cli_dependencies"] if entry["name"] == "tutti-ops"), None)
    executable = installed_command(root, item) if item else None
    if not executable:
        raise ValueError("Install tutti-ops before configuring its token.")
    origin = urlparse(args.admin_url)
    if (origin.scheme != "https" or not origin.hostname or origin.username or origin.password
            or origin.path not in ("", "/") or origin.query or origin.fragment):
        raise ValueError("Use an HTTPS admin origin without credentials, path, query or fragment.")
    target = Path.home() / ".config/tutti-ops/config.json"
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError("The tutti-ops credential location must not be a symlink.")
    previous = read_json(target) if target.exists() else {}
    if args.token_stdin:
        token = sys.stdin.readline(16385).strip()
    elif args.token_env:
        token = os.environ.get("TUTTI_ADMIN_TOKEN", "").strip()
    else:
        if not sys.stdin.isatty():
            raise ValueError("Use a local terminal, --token-stdin or --token-env for token input.")
        token = getpass.getpass("Tutti admin token (hidden): ").strip()
    if not token or len(token) > 16384 or any(char.isspace() for char in token):
        raise ValueError("Provide one nonempty token without whitespace (maximum 16384 characters).")
    env = dict(os.environ, TUTTI_ADMIN_TOKEN=token)
    env.pop("TUTTI_ADMIN_COOKIE", None)
    command = [executable, "--admin-url", args.admin_url, "--mode", "read",
               "auth", "status", "--metadata-only", "true"]
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True,
                                timeout=40, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("Token verification could not complete; existing credentials were preserved.") from None
    try:
        verified = json.loads(result.stdout)
    except (ValueError, TypeError):
        verified = {}
    if (result.returncode or not isinstance(verified, dict) or verified.get("ok") is not True
            or not isinstance(verified.get("meta"), dict)
            or verified["meta"].get("executed") is not True):
        reason = {3: "authentication rejected", 4: "permission denied", 5: "network or service failure"}.get(
            result.returncode, "unexpected verification response")
        raise ValueError(f"Token verification failed ({reason}); existing credentials were preserved.")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_json(target, {**previous, "adminUrl": args.admin_url, "token": token})
    report = {"ok": True, "authentication": "authenticated", "credential_source": "tutti-ops-config",
              "admin_url": args.admin_url, "business_logs_access": "not_checked"}
    write_json(root / "connections/tutti-ops-auth.json", report)
    emit(report)


def aws_private_executable(root):
    if os.name == "nt":
        location = os.environ.get("LOCALAPPDATA")
        if not location:
            raise ValueError("Windows AWS CLI installation requires LOCALAPPDATA.")
        return Path(location) / "Programs/Amazon/AWSCLIV2/aws.exe"
    return tool_directory(root, "aws") / "bin/aws"


def aws_version(executable):
    result = subprocess.run([str(executable), "--version"], capture_output=True,
                            text=True, check=False, timeout=30)
    match = re.search(r"aws-cli/(2\.\d+\.\d+)(?:\s|$)", result.stdout + result.stderr)
    return match.group(1) if result.returncode == 0 and match else None


def ensure_aws_cli(root, installer, install=False):
    """Reuse CLI v2 or run the reviewed official installer for the current user."""
    if (not isinstance(installer, dict) or installer.get("type") != "aws-official"
            or not re.fullmatch(r"2\.\d+\.\d+", str(installer.get("version", "")))):
        raise ValueError("AWS installer requires type aws-official and an exact CLI v2 version.")
    private = aws_private_executable(root)
    for candidate in (shutil.which("aws"), str(private) if private.is_file() else None):
        if candidate:
            version = aws_version(candidate)
            if version:
                return {"action": "reused", "executable": candidate, "version": version}
    if not install:
        return {"action": "installation_required", "executable": None, "version": None}
    system = platform.system()
    if system not in {"Darwin", "Linux", "Windows"}:
        raise ValueError("The AWS installer supports macOS, Linux and Windows.")
    key = "windows" if system == "Windows" else "unix"
    url, expected = AWS_INSTALLERS[key]
    prefix = tool_directory(root, "aws")
    prefix.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="aws-install-", dir=prefix) as directory:
        script = Path(directory) / ("install.ps1" if key == "windows" else "install.sh")
        with urlopen(url, timeout=60) as response:
            if not response.geturl().startswith("https://awscli.amazonaws.com/"):
                raise ValueError("AWS installer redirected outside its official host.")
            payload = response.read(1024 * 1024 + 1)
        if len(payload) > 1024 * 1024 or hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("Official AWS install script changed; review and update its pinned digest before running it.")
        script.write_bytes(payload)
        environment = dict(os.environ)
        if key == "windows":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            command = [shell, "-NoProfile", "-File", str(script), "-Version", installer["version"]]
        else:
            shell = shutil.which("bash")
            environment["XDG_DATA_HOME"] = str(prefix / "data")
            environment["XDG_BIN_HOME"] = str(prefix / "bin")
            command = [shell, str(script), "--version", installer["version"]]
        if not shell:
            raise ValueError("The official AWS installer needs Bash or PowerShell on this platform.")
        result = subprocess.run(command, capture_output=True, text=True, check=False,
                                env=environment, timeout=600)
        if result.returncode or not private.is_file() or aws_version(private) != installer["version"]:
            raise ValueError("AWS CLI installation or its version check failed; no successful installation was recorded.")
    write_json(prefix / "installation.json", {"installer": installer, "command": "aws",
                                              "script_url": url, "script_sha256": expected})
    return {"action": "installed", "executable": str(private), "version": installer["version"]}


def retire_owned_aws_mcp(root):
    receipt_path = root / "connections/aws-mcp.json"
    codex = shutil.which("codex")
    if not receipt_path.is_file():
        return {"action": "not_present"}
    if not codex:
        return {"action": "not_checked", "reason": "codex_unavailable"}
    receipt = read_json(receipt_path)
    name = receipt.get("server_name")
    if (not isinstance(name, str) or not NAME.fullmatch(name)
            or receipt.get("scope") != "codex_user" or receipt.get("registration") != "configured"):
        return {"action": "not_present"}
    existing = next((s for s in codex_mcp_servers(codex) if s.get("name") == name), None)
    if existing is None:
        return {"action": "not_present"}
    transport = existing.get("transport", {})
    owned_oauth = (receipt.get("auth_mode") == "oauth"
                   and receipt.get("url") in {u + "?oauth=initialize" for u in AWS_ENDPOINTS}
                   and transport.get("type") == "streamable_http"
                   and transport.get("url") == receipt["url"]
                   and not any(transport.get(k) for k in
                               ("bearer_token_env_var", "http_headers", "env_http_headers", "http_headers_helper")))
    if not owned_oauth and not owned_aws_proxy(existing, receipt_path):
        return {"action": "conflict_preserved", "server_name": name}
    result = subprocess.run([codex, "mcp", "remove", name], capture_output=True,
                            text=True, check=False, timeout=30)
    if result.returncode or any(s.get("name") == name for s in codex_mcp_servers(codex)):
        return {"action": "removal_not_confirmed", "server_name": name}
    write_json(receipt_path, {**receipt, "registration": "removed", "retired_by": "setup-aws-cli"})
    return {"action": "removed", "server_name": name}


def setup_aws_cli(args, root):
    cfg = load_config(args, root)
    defaults = read_json(PLUGIN_ROOT / "config/workbench.example.json")
    supplied = cfg.get("aws_cli", {})
    if not isinstance(supplied, dict) or set(supplied) - {"profile", "region"}:
        raise ValueError("aws_cli supports profile and region only.")
    previous = cfg.get("aws_mcp", {})
    inherited = {k: previous[k] for k in ("profile", "region") if isinstance(previous, dict) and k in previous}
    settings = {**defaults["aws_cli"], **inherited, **supplied}
    profile, region = settings["profile"], settings["region"]
    if profile is not None and (not isinstance(profile, str) or not profile.strip() or profile.startswith("-")):
        raise ValueError("AWS profile must be null or a nonempty profile name.")
    if not isinstance(region, str) or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region):
        raise ValueError("AWS CLI needs an actual operation region.")
    dependencies = cfg.setdefault("cli_dependencies", [])
    item = next((e for e in dependencies if e["name"] == "aws"), None)
    if item is None:
        item = next(e for e in defaults["cli_dependencies"] if e["name"] == "aws")
        dependencies.append(item)
    if item["command"] != "aws":
        raise ValueError("AWS CLI setup expects the aws command; preserve and review custom commands separately.")
    installer = item.get("installer") or next(e for e in defaults["cli_dependencies"] if e["name"] == "aws")["installer"]
    if not item.get("installer"):
        item["installer"] = installer
    cfg["aws_cli"] = settings
    write_json(config_path(args, root), cfg)
    prepared = ensure_aws_cli(root, installer, install=args.install)
    if not prepared["executable"]:
        emit({"ok": False, "installation": prepared, "authentication": "not_checked",
              "next_action": "Run setup-aws-cli --install to install AWS CLI v2."})
        return 2
    authentication, login_command = "not_checked", None
    if args.check_auth:
        command = [prepared["executable"], "sts", "get-caller-identity", "--output", "json",
                   "--region", region, "--no-cli-pager"]
        if profile:
            command += ["--profile", profile]
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            authentication = "authenticated" if isinstance(payload, dict) and payload.get("Account") and payload.get("Arn") else "check_failed"
        elif "sso" in result.stderr.lower() and any(t in result.stderr.lower() for t in ("expired", "refresh failed", "token does not exist")):
            authentication = "sso_login_required"
            login_command = [prepared["executable"], "sso", "login"] + (["--profile", profile] if profile else [])
        else:
            authentication = "credentials_or_network_error"
    report = {"ok": True, "transport": "cli", "installation": prepared, "settings": settings,
              "authentication": authentication, "login_command": login_command,
              "business_logs_access": "not_checked", "previous_mcp": retire_owned_aws_mcp(root),
              "next_action": "Use this executable for AWS commands; check authorization when AWS logs are needed."}
    write_json(root / "connections/aws-cli.json", report)
    emit(report)


def real_url(value):
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    host = parsed.hostname or ""
    return bool(parsed.scheme in {"https", "http"} and host and not parsed.username
                and not parsed.password and not host.endswith(".invalid")
                and host not in {"example.com", "example.org", "example.net"}
                and "your_real_host" not in host.lower() and "placeholder" not in host.lower())


def resolve_log_path(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Log path must be a nonempty string.")
    for variable in ("TMPDIR", "TEMP"):
        prefix = "${" + variable + "}/"
        if value.startswith(prefix):
            directory = os.environ.get(variable, "")
            if not directory or not Path(directory).is_absolute():
                raise ValueError(f"Log path requires an absolute {variable}.")
            value = str(Path(directory) / value[len(prefix):])
            break
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Log path must resolve to an absolute file path.")
    return path


def log_source_configured(source, cfg):
    if (not isinstance(source, dict) or not source.get("name")
            or not source.get("environment")):
        return False
    transport = source.get("transport", "cli")
    if transport == "browser-webmcp":
        bridge = source.get("browser_bridge")
        if (source.get("tool") != "get_web_logs" or not isinstance(bridge, dict)
                or not all(isinstance(bridge.get(key), str) and bridge[key].strip()
                           for key in ("list_pages_tool", "list_tools_tool", "execute_tool"))):
            return False
        if bridge.get("kind") == "host-tools":
            return True
        if bridge.get("kind") == "mcp":
            return log_source_configured({"name": source["name"], "environment": source["environment"],
                                          "transport": "mcp", "mcp_server": bridge.get("mcp_server"),
                                          "tool": bridge["execute_tool"]}, cfg)
        return False
    if transport == "files":
        if "paths" in source:
            paths = source["paths"]
            if not isinstance(paths, list) or not paths:
                return False
            try:
                for path in paths:
                    resolve_log_path(path)
            except (ValueError, RuntimeError):
                return False
            return True
        paths = source.get("relative_paths")
        location = source.get("root") or source.get("root_env") or source.get("default_root")
        return bool(isinstance(location, str) and location and isinstance(paths, list)
                    and paths and all(isinstance(path, str) and path for path in paths))
    if transport == "mcp":
        servers = cfg.get("mcp_servers", {})
        name = source.get("mcp_server")
        tool = source.get("tool")
        if (not isinstance(servers, dict) or not isinstance(name, str)
                or not isinstance(tool, str) or not tool):
            return False
        server = servers.get(name)
        if not isinstance(server, dict):
            return False
        if server.get("type") == "streamable-http":
            return real_url(server.get("url"))
        return bool(server.get("type") == "stdio" and server.get("command"))
    argv = source.get("argv")
    return bool(transport == "cli" and isinstance(argv, list) and argv
                and all(isinstance(arg, str) and arg for arg in argv))


def doctor(args, root):
    cfg = load_config(args, root)
    dependencies = []
    for item in cfg.get("cli_dependencies", []):
        command = installed_command(root, item)
        dependencies.append({"name": item["name"], "available": command is not None,
                             "required": bool(item.get("required", True)),
                             "executable": command, "version": "not_checked"})
    feishu = cfg.get("feishu", {})
    repositories = cfg.get("repositories", [])
    logs = cfg.get("log_sources", [])
    log_reports = [{"name": source.get("name") if isinstance(source, dict) else None,
                    "transport": source.get("transport", "cli") if isinstance(source, dict) else None,
                    "configured": log_source_configured(source, cfg), "source_access": "not_checked"}
                   for source in logs]
    validation = cfg.get("validation", {})
    configured = {
        "feishu": bool(real_url(feishu.get("base_url")) and feishu.get("table_id")
                       and feishu.get("field_map")),
        "repositories": bool(repositories and all(
            isinstance(repo, dict) and repo.get("name") and repo.get("url")
            and repo.get("base_branch") for repo in repositories)),
        "logs": bool(log_reports and all(source["configured"] for source in log_reports)),
        "validation": bool(real_url(validation.get("url")) and validation.get("environment")
                           and validation.get("revision_source") and validation.get("browser_tool")),
    }
    tools_ready = all(item["available"] or not item["required"] for item in dependencies)
    emit({"local_tools_ready": tools_ready, "cli_dependencies": dependencies,
          "integrations_configured": configured, "log_sources": log_reports,
          "external_connections": "not_checked",
          "ready_for_full_workflow": tools_ready and all(configured.values()),
          "trigger_mode": cfg.get("trigger", {}).get("mode", "manual"),
          "automatic_trigger_available": False})


def setup_aws_mcp(args, root):
    cfg = load_config(args, root)
    settings = cfg.get("aws_mcp", {})
    if not isinstance(settings, dict):
        raise ValueError("aws_mcp must be an object.")
    mode = settings.get("auth_mode", "oauth")
    if mode == "oauth":
        return setup_aws_oauth(args, root)
    if mode == "sigv4":
        return setup_aws_sigv4(args, root)
    raise ValueError("AWS MCP auth_mode must be oauth or sigv4.")


def codex_mcp_servers(codex):
    result = subprocess.run([codex, "mcp", "list", "--json"], capture_output=True,
                            text=True, check=False, timeout=30)
    if result.returncode:
        raise ValueError("Unable to inspect existing Codex MCP registrations.")
    servers = json.loads(result.stdout)
    if not isinstance(servers, list) or not all(isinstance(s, dict) for s in servers):
        raise ValueError("Unexpected Codex MCP listing format.")
    return servers


def owned_aws_proxy(server, receipt_path):
    """Only migrate the exact proxy recorded by this plugin's previous setup."""
    if not receipt_path.is_file():
        return False
    receipt = read_json(receipt_path)
    previous = receipt.get("settings", {})
    if (receipt.get("server_name") != server.get("name") or receipt.get("scope") != "codex_user"
            or receipt.get("registration") != "configured" or receipt.get("read_only") is not True
            or not isinstance(previous, dict) or previous.get("endpoint") not in AWS_ENDPOINTS
            or not isinstance(previous.get("region"), str)):
        return False
    expected = ["--native-tls", AWS_PROXY, previous["endpoint"], "--read-only",
                "--metadata", "AWS_REGION=" + previous["region"]]
    if previous.get("profile") is not None:
        expected += ["--profile", previous["profile"]]
    transport = server.get("transport", {})
    return bool(server.get("enabled") is True and transport.get("type") == "stdio"
                and isinstance(transport.get("command"), str)
                and Path(transport["command"]).name in {"uvx", "uvx.exe"}
                and transport.get("args") == expected and not transport.get("env")
                and not transport.get("env_vars") and not transport.get("cwd"))


def setup_aws_oauth(args, root):
    """Register the remote OAuth endpoint; Codex owns tokens and browser consent."""
    cfg = load_config(args, root)
    defaults = read_json(PLUGIN_ROOT / "config/workbench.example.json")["aws_mcp"]
    supplied = cfg.get("aws_mcp", {})
    if not isinstance(supplied, dict) or set(supplied) - set(defaults):
        raise ValueError("Unsupported aws_mcp setting.")
    settings = {**defaults, **supplied, "auth_mode": "oauth"}
    name, endpoint = settings["server_name"], settings["endpoint"]
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("AWS MCP needs a valid server_name.")
    if endpoint not in AWS_ENDPOINTS:
        raise ValueError("Use a verified official AWS MCP endpoint.")
    if name in cfg.get("mcp_servers", {}):
        raise ValueError("AWS MCP is host-managed; remove its duplicate plugin MCP definition first.")
    codex = shutil.which("codex")
    if not codex:
        emit({"ok": False, "registration": "pending_dependencies", "missing": ["codex"],
              "connection": "not_checked"})
        return 2
    url = endpoint + "?oauth=initialize"

    def matching(server):
        transport = server.get("transport", {})
        return bool(server.get("enabled") is True
                    and transport.get("type") == "streamable_http" and transport.get("url") == url
                    and not any(transport.get(key) for key in
                                ("bearer_token_env_var", "http_headers", "env_http_headers", "http_headers_helper")))

    existing = next((s for s in codex_mcp_servers(codex) if s.get("name") == name), None)
    migration = bool(existing is not None and owned_aws_proxy(existing, root / "connections/aws-mcp.json"))
    if existing is not None and not matching(existing) and not migration:
        emit({"ok": False, "registration": "conflict_preserved", "server_name": name,
              "connection": "not_checked", "next_action": "Review the existing server or use a different server_name."})
        return 2
    action, add_status = "reused", "not_needed"
    if existing is None or migration:
        # Some Codex versions start OAuth during add. Registration can persist even
        # when browser consent is pending, fails, or exceeds this bounded operation.
        try:
            added = subprocess.run([codex, "mcp", "add", name, "--url", url],
                                   capture_output=True, text=True, check=False, timeout=30)
            add_status = "completed" if added.returncode == 0 else "auth_or_registration_error"
        except subprocess.TimeoutExpired:
            add_status = "login_pending_or_timeout"
        action = "migrated_to_oauth" if migration else "registered"
    current = next((s for s in codex_mcp_servers(codex) if s.get("name") == name), None)
    if current is None or not matching(current):
        emit({"ok": False, "registration": "not_confirmed", "server_name": name,
              "add_status": add_status, "connection": "not_checked",
              "next_action": "Inspect Codex MCP configuration before retrying; registration or login may have failed."})
        return 2
    cfg["aws_mcp"] = settings
    write_json(config_path(args, root), cfg)
    authentication = ("oauth_credentials_present" if current.get("auth_status") == "oauth"
                      else "oauth_login_required")
    report = {"ok": True, "action": action, "server_name": name, "scope": "codex_user",
              "registration": "configured", "transport": "streamable_http", "auth_mode": "oauth",
              "url": url, "authentication": authentication, "connection": "not_checked",
              "add_status": add_status, "read_only": "workflow_policy_only", "read_only_enforced": False,
              "login_command": ["codex", "mcp", "login", name], "settings": settings,
              "next_action": "Complete Codex MCP OAuth consent if needed; discover tools and verify a read-only call and account."}
    write_json(root / "connections/aws-mcp.json", {**report, "checked_at": datetime.now().astimezone().isoformat()})
    emit(report)


def setup_aws_sigv4(args, root):
    """Register a read-only AWS proxy in the host, without editing plugin caches."""
    cfg = load_config(args, root)
    defaults = read_json(PLUGIN_ROOT / "config/workbench.example.json")["aws_mcp"]
    settings = cfg.get("aws_mcp", defaults)
    if not isinstance(settings, dict) or set(settings) - set(defaults):
        raise ValueError("Unsupported aws_mcp setting.")
    settings = {**defaults, **settings}
    name, endpoint, region, profile = (settings[key] for key in
                                       ("server_name", "endpoint", "region", "profile"))
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("AWS MCP needs a valid server_name.")
    if endpoint not in AWS_ENDPOINTS:
        raise ValueError("Use a verified official AWS MCP endpoint.")
    if not isinstance(region, str) or not re.fullmatch(r"[a-z]{2}(?:-[a-z]+)+-\d+", region):
        raise ValueError("AWS MCP needs an actual AWS operation region.")
    if profile is not None and (not isinstance(profile, str) or not profile.strip()
                                or profile.startswith("-")):
        raise ValueError("AWS profile must be null or a nonempty profile name.")
    if name in cfg.get("mcp_servers", {}):
        raise ValueError("AWS MCP is host-managed; remove its duplicate plugin MCP definition first.")
    codex, uvx = shutil.which("codex"), shutil.which("uvx")
    if not codex or not uvx:
        emit({"ok": False, "registration": "pending_dependencies",
              "missing": [key for key, value in (("codex", codex), ("uvx", uvx)) if not value],
              "connection": "not_checked"})
        return 2
    proxy_args = ["--native-tls", AWS_PROXY, endpoint, "--read-only",
                  "--metadata", "AWS_REGION=" + region]
    if profile is not None:
        proxy_args += ["--profile", profile]

    def host_servers():
        return codex_mcp_servers(codex)

    def matching(server):
        transport = server.get("transport", {})
        return bool(server.get("enabled") is True and transport.get("type") == "stdio"
                    and transport.get("command") == uvx and transport.get("args") == proxy_args
                    and not transport.get("env") and not transport.get("env_vars")
                    and not transport.get("cwd"))

    existing = next((s for s in host_servers() if s.get("name") == name), None)
    if existing is not None and not matching(existing):
        emit({"ok": False, "registration": "conflict_preserved", "server_name": name,
              "connection": "not_checked", "next_action": "Review the existing server or use a different server_name."})
        return 2
    # Cache the fixed official distribution and verify its actual entrypoint before registration.
    prepared = subprocess.run([uvx, "--native-tls", AWS_PROXY, "--help"],
                              capture_output=True, text=True, check=False, timeout=180)
    if prepared.returncode or "--read-only" not in prepared.stdout:
        emit({"ok": False, "registration": "runtime_unavailable", "server_name": name,
              "connection": "not_checked", "next_action": "Check uvx package download, Python and TLS trust."})
        return 2
    action = "reused"
    if existing is None:
        added = subprocess.run([codex, "mcp", "add", name, "--", uvx, *proxy_args],
                               capture_output=True, text=True, check=False, timeout=30)
        if added.returncode:
            raise ValueError("Codex did not complete AWS MCP registration; inspect the host before retrying.")
        action = "registered"
    current = next((s for s in host_servers() if s.get("name") == name), None)
    if current is None or not matching(current):
        raise ValueError("AWS MCP registration could not be confirmed in Codex.")
    cfg["aws_mcp"] = settings
    write_json(config_path(args, root), cfg)
    authentication = "not_checked"
    login_command = None
    aws = shutil.which("aws")
    if aws:
        identity_args = [aws, "sts", "get-caller-identity", "--output", "json", "--no-cli-pager"]
        if profile is not None:
            identity_args += ["--profile", profile]
        try:
            identity = subprocess.run(identity_args, capture_output=True, text=True,
                                      check=False, timeout=30)
            if identity.returncode == 0:
                payload = json.loads(identity.stdout)
                authentication = ("cli_credentials_valid" if payload.get("Account") and payload.get("Arn")
                                  else "check_failed")
            elif "sso" in identity.stderr.lower() and any(
                    text in identity.stderr.lower() for text in ("expired", "refresh failed", "token does not exist")):
                authentication = "sso_login_required"
                login_command = ["aws", "sso", "login"] + (["--profile", profile] if profile else [])
            else:
                authentication = "credentials_or_network_error"
        except (subprocess.TimeoutExpired, ValueError, OSError):
            authentication = "check_failed"
    report = {"ok": True, "action": action, "server_name": name, "scope": "codex_user",
              "registration": "configured", "runtime": "prepared", "read_only": True,
              "authentication": authentication, "connection": "not_checked",
              "login_command": login_command, "settings": settings,
              "next_action": "Refresh credentials if needed; reload MCP in Codex, discover tools and make a read-only call."}
    write_json(root / "connections/aws-mcp.json", {**report, "checked_at": datetime.now().astimezone().isoformat()})
    emit(report)


def bug_directory(root, bug_id):
    if not NAME.fullmatch(bug_id):
        raise ValueError("Bug ID must use 1-64 letters, digits, hyphens or underscores.")
    directory = (root / "bugs" / bug_id).resolve()
    if root not in directory.parents:
        raise ValueError("Bug path escapes data directory.")
    return directory


def new_bug(args, root):
    directory = bug_directory(root, args.bug_id)
    if directory.exists():
        emit({"bug_dir": str(directory), "action": "preserved"})
        return
    directory.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".new-bug-", dir=directory.parent))
    try:
        dossier = read_json(PLUGIN_ROOT / "assets/bug.json")
        dossier["bug_id"] = args.bug_id
        dossier["source_url"] = args.source_url
        write_json(temporary / "bug.json", dossier)
        for name in (*ARTIFACTS, "verification.md"):
            shutil.copyfile(PLUGIN_ROOT / "assets" / name, temporary / name)
        (temporary / "dialogue.jsonl").touch()
        (temporary / "evidence").mkdir()
        temporary.rename(directory)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    emit({"bug_dir": str(directory), "action": "created", "status": "pending_analysis"})


def artifact_hashes(directory):
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in ARTIFACTS}


def positive_int(value):
    return type(value) is int and value > 0


def execution_errors(directory, expected_id):
    bug = read_json(directory / "bug.json")
    errors = []
    if bug.get("bug_id") != expected_id:
        errors.append("Bug ID differs from the requested dossier.")
    if not positive_int(bug.get("input_revision")):
        errors.append("QA input must have a positive revision.")
    if bug.get("pending_questions"):
        errors.append("Outstanding context questions must be resolved first.")
    root = bug.get("root_cause", {})
    plan = bug.get("plan", {})
    acceptance = bug.get("acceptance", {})
    if root.get("status") != "confirmed" or not positive_int(root.get("version")):
        errors.append("Root cause is not confirmed and versioned.")
    if root.get("input_revision") != bug.get("input_revision"):
        errors.append("Root cause does not cover the latest QA input.")
    if plan.get("status") != "approved" or not positive_int(plan.get("version")):
        errors.append("Plan is not marked approved and versioned.")
    if plan.get("root_cause_version") != root.get("version"):
        errors.append("Plan references a different root-cause version.")
    if (not positive_int(acceptance.get("version"))
            or acceptance.get("plan_version") != plan.get("version")):
        errors.append("Acceptance criteria are missing or reference a different plan.")
    baselines = bug.get("baselines")
    if (not isinstance(baselines, dict) or not baselines
            or not all(NAME.fullmatch(key) and isinstance(value, str) and SHA.fullmatch(value)
                       for key, value in baselines.items())):
        errors.append("Record full commit SHAs for all relevant repository baselines.")
    approval_path = directory / "approval.json"
    if not approval_path.is_file():
        errors.append("A real RD approval receipt is required.")
        return errors
    approval = read_json(approval_path)
    bindings = {"bug_id": expected_id, "input_revision": bug.get("input_revision"),
                "root_cause_version": root.get("version"), "plan_version": plan.get("version"),
                "acceptance_version": acceptance.get("version"), "baselines": baselines}
    if approval.get("decision") != "approved":
        errors.append("RD did not approve execution.")
    for key, value in bindings.items():
        if approval.get(key) != value:
            errors.append(f"Approval binding is stale: {key}.")
    actor = approval.get("actor", {})
    source = approval.get("source", {})
    if not isinstance(actor, dict) or actor.get("role") != "RD" or not actor.get("id"):
        errors.append("RD actor reference is missing.")
    if (not isinstance(source, dict) or source.get("kind") not in {"feishu_record", "codex_user_message"}
            or not source.get("reference")):
        errors.append("Original approval source is missing.")
    try:
        approved_at = datetime.fromisoformat(str(approval.get("approved_at", "")).replace("Z", "+00:00"))
        if approved_at.tzinfo is None:
            raise ValueError("Timezone is missing.")
    except ValueError:
        errors.append("Approval timestamp must include a timezone.")
    if approval.get("artifact_sha256") != artifact_hashes(directory):
        errors.append("Reports changed after approval or their SHA-256 values are missing.")
    return errors


def check_execution(args, root):
    directory = bug_directory(root, args.bug_id)
    errors = execution_errors(directory, args.bug_id)
    emit({"consistent": not errors, "errors": errors,
          "approval_identity_verified": False,
          "next_action": "Verify original RD approval and actual Git baselines before editing."
                         if not errors else "Resolve handoff inconsistencies before execution."})
    return 2 if errors else 0


def install_cli(args, root):
    cfg = load_config(args, root)
    item = next((entry for entry in cfg.get("cli_dependencies", []) if entry["name"] == args.name), None)
    if item is None:
        raise ValueError("CLI is not declared in this configuration.")
    installer = item.get("installer")
    if isinstance(installer, dict) and installer.get("type") == "npm-global":
        if item["name"] != "tutti-ops" or item["command"] != "tutti-ops" or installer != TUTTI_OPS_INSTALLER:
            raise ValueError("The global npm installer is reserved for @tutti-os/tutti-ops-cli.")
        emit({"name": "tutti-ops", **ensure_tutti_ops(root, install=True), "authentication": "not_checked"})
        return
    if isinstance(installer, dict) and installer.get("type") == "aws-official":
        if item["name"] != "aws" or item["command"] != "aws":
            raise ValueError("The official AWS installer only installs the aws command.")
        emit({"name": "aws", **ensure_aws_cli(root, installer, install=True), "authentication": "not_checked"})
        return
    if installer is None:
        command = installed_command(root, item)
        if command:
            emit({"name": args.name, "action": "reused", "executable": command})
            return
        raise ValueError("Configure a verified fixed-version installer for this missing CLI.")
    if (not isinstance(installer, dict) or installer.get("type") != "npm"
            or not PACKAGE.fullmatch(str(installer.get("package", "")))
            or not VERSION.fullmatch(str(installer.get("version", "")))
            or not NAME.fullmatch(item["command"])):
        raise ValueError("npm installer requires a package name, exact version and simple executable name.")
    prefix = tool_directory(root, item["name"])
    executable = tool_bin(prefix, item["command"])
    receipt = prefix / "installation.json"
    if receipt.is_file() and executable.is_file() and read_json(receipt).get("installer") == installer:
        emit({"name": args.name, "action": "reused", "executable": str(executable)})
        return
    npm = shutil.which("npm")
    if npm is None:
        raise ValueError("npm must already be available to use the npm installer.")
    prefix.mkdir(parents=True, exist_ok=True)
    package = installer["package"] + "@" + installer["version"]
    command = [npm, "install", "--prefix", str(prefix), "--ignore-scripts", "--no-audit", "--no-fund", package]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300, check=False)
    if result.returncode or not executable.is_file():
        raise ValueError("CLI installation failed or did not provide the configured executable; inspect npm locally.")
    write_json(receipt, {"installer": installer, "command": item["command"]})
    emit({"name": args.name, "action": "installed", "executable": str(executable),
          "package": package, "authentication": "not_checked"})


def validate_servers(servers):
    if not isinstance(servers, dict):
        raise ValueError("mcp_servers must be an object.")
    for name, server in servers.items():
        if not NAME.fullmatch(name) or not isinstance(server, dict):
            raise ValueError("MCP servers need valid names and object definitions.")
        kind = server.get("type")
        if kind == "streamable-http":
            if set(server) - {"type", "url"}:
                raise ValueError("Configure MCP authentication and advanced HTTP settings in the host.")
            if not real_url(server.get("url")):
                raise ValueError("MCP URL must be a real endpoint, without embedded credentials.")
            parsed = urlparse(server["url"])
            if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Remote MCP endpoints require HTTPS; HTTP is allowed for loopback only.")
            if parsed.query or parsed.fragment:
                raise ValueError("Use a plain MCP endpoint; put credentials in host authentication storage.")
        elif kind == "stdio":
            if set(server) - {"type", "command", "args", "cwd"}:
                raise ValueError("This generator supports stdio command, args and cwd; configure secrets in the host.")
            if not isinstance(server.get("command"), str) or not server["command"]:
                raise ValueError("STDIO MCP needs its actual startup command.")
            if not isinstance(server.get("args", []), list) or not all(isinstance(x, str) for x in server.get("args", [])):
                raise ValueError("STDIO MCP args must be a string array.")
            if "cwd" in server and not isinstance(server["cwd"], str):
                raise ValueError("STDIO MCP cwd must be a string.")
        else:
            raise ValueError("Supported MCP transports: streamable-http, stdio.")


def configure_mcp(args, root):
    cfg = load_config(args, root)
    servers = cfg.get("mcp_servers", {})
    validate_servers(servers)
    target = Path(args.output_dir).expanduser().resolve()
    if ".codex" in target.parts and "cache" in target.parts:
        raise ValueError("Generate MCP configuration in source, not the installed plugin cache.")
    manifest = read_json(target / "plugin.json")
    if manifest.get("name") != read_json(PLUGIN_ROOT / "plugin.json").get("name"):
        raise ValueError("Output must be this plugin's source directory.")
    portable = {"$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json", "mcpServers": servers}
    legacy = {"mcpServers": {name: {key: value for key, value in server.items() if key != "type"}
                              for name, server in servers.items()}}
    write_json(target / "mcp.json", portable)
    write_json(target / ".mcp.json", legacy)
    emit({"action": "generated", "output_dir": str(target), "servers": list(servers),
          "connections": "not_checked", "next_action": "Reload or reinstall the plugin from source."})


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    for name in ("init", "doctor", "new-bug", "artifact-hashes", "check-execution", "install-cli", "configure-mcp", "setup-aws-mcp", "setup-aws-cli", "setup-tutti-ops", "configure-tutti-token"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name in {"new-bug", "artifact-hashes", "check-execution"}:
            command.add_argument("--bug-id", required=True)
        if name == "new-bug":
            command.add_argument("--source-url")
        if name == "install-cli":
            command.add_argument("--name", required=True)
        if name == "configure-mcp":
            command.add_argument("--output-dir", required=True)
        if name == "setup-aws-cli":
            command.add_argument("--install", action="store_true", help="Install official CLI v2 if none is available.")
            command.add_argument("--check-auth", action="store_true", help="Run a read-only identity check; never start login.")
        if name == "setup-tutti-ops":
            command.add_argument("--install", action="store_true", help="Install @tutti-os/tutti-ops-cli globally if missing.")
        if name == "configure-tutti-token":
            command.add_argument("--admin-url", default="https://admin.tutti.sh")
            source = command.add_mutually_exclusive_group()
            source.add_argument("--token-stdin", action="store_true", help="Read a token from standard input.")
            source.add_argument("--token-env", action="store_true", help="Read TUTTI_ADMIN_TOKEN; save after verification.")
    return result


def main():
    args = parser().parse_args()
    try:
        root = data_root(args)
        operations = {"init": initialize, "doctor": doctor, "new-bug": new_bug,
                      "check-execution": check_execution, "install-cli": install_cli,
                      "configure-mcp": configure_mcp, "setup-aws-mcp": setup_aws_mcp,
                      "setup-aws-cli": setup_aws_cli, "setup-tutti-ops": setup_tutti_ops,
                      "configure-tutti-token": configure_tutti_token}
        if args.operation == "artifact-hashes":
            emit({"artifact_sha256": artifact_hashes(bug_directory(root, args.bug_id))})
        else:
            return operations[args.operation](args, root) or 0
    except (ValueError, OSError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
        emit({"ok": False, "error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
