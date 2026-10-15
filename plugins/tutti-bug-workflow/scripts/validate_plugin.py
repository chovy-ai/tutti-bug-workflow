#!/usr/bin/env python3
"""Check package identity, scene discovery, compatibility and contained references."""

import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
SCENES = {"bug-investigate", "bug-analyze", "bug-execute", "bug-setup"}


def main():
    errors = []
    root = json.loads((ROOT / "plugin.json").read_text())
    legacy = json.loads((ROOT / ".codex-plugin/plugin.json").read_text())
    portable_mcp = json.loads((ROOT / "mcp.json").read_text())
    legacy_mcp = json.loads((ROOT / ".mcp.json").read_text())
    for key in ("name", "version", "description"):
        if root.get(key) != legacy.get(key):
            errors.append(f"Manifest mismatch: {key}")
    if root.get("name") != ROOT.name or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", root.get("name", "")):
        errors.append("Plugin directory and valid name must match.")
    if not re.fullmatch(r"\d+\.\d+\.\d+", root.get("version", "")):
        errors.append("Use a semantic version.")
    interface = root.get("extensions", {}).get("com.openai", {}).get("interface", {})
    if interface != legacy.get("interface"):
        errors.append("Compatibility interface differs.")
    if len(interface.get("shortDescription", "")) > 30:
        errors.append("Plugin subtitle is too long.")
    if any(key in root for key in ("skills", "mcpServers", "apps", "interface")):
        errors.append("Portable manifest contains legacy top-level fields.")
    converted = {name: {key: value for key, value in server.items() if key != "type"}
                 for name, server in portable_mcp.get("mcpServers", {}).items()}
    if converted != legacy_mcp.get("mcpServers"):
        errors.append("Portable/compatibility MCP configurations differ.")
    catalog = json.loads((ROOT / "skills/bug-setup/config/tool-profiles.json").read_text())
    scene_names = {"investigate", "analyze", "execute"}
    if catalog.get("schema_version") != 1 or set(catalog.get("scenes", {})) != scene_names:
        errors.append("Invalid tool scene catalog.")
    identifiers = set()
    for tool in catalog.get("tools", []):
        identifier = tool.get("id")
        required, conditional = set(tool.get("required_in", [])), set(tool.get("conditional_in", []))
        if (not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", identifier)
                or identifier in identifiers or not (required | conditional)
                or (required | conditional) - scene_names or required & conditional
                or not tool.get("requirements") or not isinstance(tool.get("commands"), list)
                or tool.get("install_operation") not in (None, "setup-tutti-ops")):
            errors.append(f"Invalid tool definition: {identifier}")
        identifiers.add(identifier)
    actual = {p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md")}
    if actual != SCENES:
        errors.append("Expected only bug-investigate, bug-analyze, bug-execute and bug-setup under skills/.")
    for name in actual:
        file = ROOT / "skills" / name / "SKILL.md"
        body = file.read_text()
        if not body.startswith("---\n"):
            errors.append(f"Frontmatter missing: {name}")
        elif not re.search(rf"^name: {re.escape(name)}$", body, re.M) or not re.search(r"^description: .+", body, re.M):
            errors.append(f"Invalid skill name/description: {name}")
        if not (file.parent / "agents/openai.yaml").is_file():
            errors.append(f"UI metadata missing: {name}")
    for file in ROOT.rglob("*.md"):
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", file.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            path = (file.parent / target.split("#")[0]).resolve()
            if ROOT not in path.parents or not path.exists():
                errors.append(f"Missing or escaping reference: {file.relative_to(ROOT)} -> {target}")
    for file in ROOT.rglob("*"):
        if file.is_symlink():
            errors.append(f"Symlink in distributable package: {file.relative_to(ROOT)}")
    print(json.dumps({"valid": not errors, "skills": sorted(actual), "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
