#!/usr/bin/env python3
"""Plan scene-specific tool preparation without installation, login or network calls."""

import argparse
from pathlib import Path
import shutil
import sys

import workbench

ROOT = Path(__file__).resolve().parents[1]
# bug-solution is paused (moved to disabled-skills/); add "solution" back here to re-enable it.
ENABLED_SCENES = ("investigate", "execute")


def configuration_status(kind, cfg):
    if kind == "feishu":
        value = cfg.get("bug_report", {})
        configured = bool(workbench.real_url(value.get("base_url")) and value.get("table_id")
                          and value.get("field_map"))
    elif kind == "repositories":
        repos = cfg.get("repositories", [])
        configured = bool(repos and all(isinstance(r, dict) and r.get("name") and r.get("url")
                                       and r.get("base_branch") for r in repos))
    elif kind == "validation":
        value = cfg.get("validation", {})
        configured = bool(workbench.real_url(value.get("url")) and value.get("environment")
                          and value.get("revision_source") and value.get("browser_tool"))
    elif kind.startswith("source:"):
        name = kind.split(":", 1)[1]
        source = next((s for s in cfg.get("log_sources", [])
                       if isinstance(s, dict) and s.get("name") == name), {})
        configured = workbench.log_source_configured(source, cfg)
    elif kind == "source-only":
        return {"status": "source_generation", "rendering": "not_checked"}
    else:
        return {"status": "not_checked", "scope": kind}
    return {"status": "configured" if configured else "pending_configuration"}


def command_status(name, root, cfg):
    item = next((d for d in cfg.get("cli_dependencies", []) if d.get("name") == name), None)
    executable = workbench.installed_command(root, item) if item else shutil.which(name)
    return {"name": name, "executable": executable, "available": executable is not None,
            "version": "not_checked"}


def installation_plan(tool, root, cfg):
    operation = tool["install_operation"]
    if operation is None:
        return None
    name = tool["commands"][0]
    item = next((d for d in cfg.get("cli_dependencies", []) if d.get("name") == name), {})
    if item.get("command", name) != name:
        return {"status": "review_custom_configuration"}
    installer = item.get("installer")
    if name == "tutti-ops" and installer not in (None, workbench.TUTTI_OPS_INSTALLER):
        return {"status": "review_custom_configuration"}
    command = [sys.executable, str(ROOT / "scripts/workbench.py"), operation,
               "--data-dir", str(root), "--install"]
    return {"status": "available", "argv": command, "executed": False}


def build_report(scene, include, root, cfg, config=None):
    catalog = workbench.read_json(ROOT / "config/tool-profiles.json")
    scenes = list(ENABLED_SCENES) if scene == "all" else [scene]
    applicable = [t for t in catalog["tools"]
                  if set(scenes) & set(t["required_in"] + t["conditional_in"])]
    unknown = set(include) - {t["id"] for t in applicable}
    if unknown:
        raise ValueError("Tools do not apply to this scene or are unknown: " + ", ".join(sorted(unknown)))
    tools = []
    for tool in applicable:
        required = bool(set(scenes) & set(tool["required_in"]))
        selected = required or tool["id"] in include
        plan = installation_plan(tool, root, cfg) if selected else None
        if plan and plan.get("argv") and config:
            plan["argv"] += ["--config", str(Path(config).expanduser().resolve())]
        tools.append({"id": tool["id"], "label": tool["label"],
                      "requirement": "required" if required else "conditional", "selected": selected,
                      "requirements": tool["requirements"],
                      "commands": [command_status(n, root, cfg) for n in tool["commands"]] if selected else [],
                      "configuration": configuration_status(tool["configuration"], cfg) if selected
                      else {"status": "not_selected"},
                      "install_plan": plan, "authentication": "not_checked", "business_access": "not_checked"})
    return {"scene": scene, "mode": "inventory", "data_dir": str(root),
            "python": {"executable": sys.executable, "supported": sys.version_info >= (3, 10)},
            "tools": tools, "external_connections": "not_checked", "installation_performed": False,
            "next_action": "Review selected tools, resolve pending providers, then run the approved preparation steps."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", choices=(*ENABLED_SCENES, "all"), required=True)
    parser.add_argument("--include", action="append", default=[], metavar="TOOL_ID",
                        help="Select a conditional tool; repeat for several tools.")
    parser.add_argument("--data-dir")
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        root = workbench.data_root(args)
        report = build_report(args.scene, args.include, root, workbench.load_config(args, root), args.config)
        workbench.emit(report)
    except (ValueError, OSError, TypeError, AttributeError) as error:
        workbench.emit({"ok": False, "error": str(error), "installation_performed": False})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
