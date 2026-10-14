#!/usr/bin/env python3
"""Local configuration, tool installation and integration checks; Python standard library only."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlparse

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
CHROME_DEVTOOLS_MCP = {"type": "stdio", "command": "npx",
                       "args": ["-y", "chrome-devtools-mcp@1.10.1", "--autoConnect",
                                "--categoryExperimentalWebmcp"]}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
PACKAGE = re.compile(r"(?:@[a-z0-9_.-]+/)?[a-z0-9][a-z0-9_.-]*\Z")
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?\Z")
TUTTI_OPS_INSTALLER = {"type": "npm-global", "package": "@tutti-os/tutti-ops-cli"}


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
    (root / "tools").mkdir(parents=True, exist_ok=True)
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
        executable = tool_bin(prefix, item["command"])
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
    if transport == "user-export":
        # QA exports the archive from Tutti Settings → Diagnostics; nothing to connect.
        return True
    if transport == "chrome-devtools-mcp":
        # Registered by the plugin; Chrome WebMCP and remote-debugging consent are checked live.
        return source.get("mcp_server") == "chrome-devtools"
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
    repositories = cfg.get("repositories", [])
    logs = cfg.get("log_sources", [])
    log_reports = [{"name": source.get("name") if isinstance(source, dict) else None,
                    "transport": source.get("transport", "cli") if isinstance(source, dict) else None,
                    "configured": log_source_configured(source, cfg), "source_access": "not_checked"}
                   for source in logs]
    validation = cfg.get("validation", {})
    configured = {
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
    if "chrome-devtools" in servers and servers["chrome-devtools"] != CHROME_DEVTOOLS_MCP:
        raise ValueError("chrome-devtools is the plugin-owned Chrome WebMCP entry.")
    servers = {**servers, "chrome-devtools": CHROME_DEVTOOLS_MCP}
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
    for name in ("init", "doctor", "install-cli", "configure-mcp", "setup-tutti-ops", "configure-tutti-token"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name == "install-cli":
            command.add_argument("--name", required=True)
        if name == "configure-mcp":
            command.add_argument("--output-dir", required=True)
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
        operations = {"init": initialize, "doctor": doctor, "install-cli": install_cli,
                      "configure-mcp": configure_mcp, "setup-tutti-ops": setup_tutti_ops,
                      "configure-tutti-token": configure_tutti_token}
        return operations[args.operation](args, root) or 0
    except (ValueError, OSError, TypeError, AttributeError, subprocess.TimeoutExpired) as error:
        emit({"ok": False, "error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
