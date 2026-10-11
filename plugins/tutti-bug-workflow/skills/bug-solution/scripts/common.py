"""Shared helpers for this skill's scripts: configuration, data directory and JSON output."""

import json
import os
from pathlib import Path
import re
import tempfile

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


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
