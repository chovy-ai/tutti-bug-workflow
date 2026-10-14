#!/usr/bin/env python3
"""Render Mermaid diagrams to PNG with mermaid-cli (mmdc) and check the output.

Each input `.mmd` file becomes a PNG next to it, or in --output-dir. A syntax error
fails that file with mmdc's message so the agent can fix the source and re-run.
"""

import argparse
import os
from pathlib import Path
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as wb  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n"


def mmdc_command(cfg):
    command = os.environ.get("MMDC")
    if not command:
        command = next((item["command"] for item in cfg.get("cli_dependencies", [])
                        if item.get("name") == "mmdc"), "mmdc")
    return command


def png_size(path):
    header = path.read_bytes()[:24]
    if len(header) < 24 or header[:8] != PNG:
        return None
    return struct.unpack(">II", header[16:24])


def render(command, source, target, scale):
    result = subprocess.run([command, "-i", str(source), "-o", str(target), "-b", "white", "-s", str(scale)],
                            capture_output=True, text=True, timeout=180, check=False)
    size = png_size(target) if target.is_file() else None
    if result.returncode or not size:
        message = (result.stderr or result.stdout).strip()[-800:]
        return {"source": str(source), "ok": False, "error": message or "mmdc produced no PNG"}
    return {"source": str(source), "ok": True, "png": str(target), "width": size[0], "height": size[1],
            "bytes": target.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    parser.add_argument("--config")
    parser.add_argument("--input", action="append", required=True, help="Mermaid source (.mmd); repeatable.")
    parser.add_argument("--output-dir", help="Default: next to each input.")
    parser.add_argument("--scale", type=int, default=2)
    args = parser.parse_args()
    try:
        root = wb.data_root(args)
        try:
            cfg = wb.load_config(args, root)
        except FileNotFoundError:
            cfg = {}
        command = mmdc_command(cfg)
        results = []
        for raw in args.input:
            source = Path(raw).expanduser().resolve()
            if not source.is_file():
                raise ValueError(f"Not a file: {source}")
            folder = Path(args.output_dir).expanduser().resolve() if args.output_dir else source.parent
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / (source.stem + ".png")
            target.unlink(missing_ok=True)
            results.append(render(command, source, target, args.scale))
    except FileNotFoundError as error:
        wb.emit({"ok": False, "error": f"mmdc not found ({error}); install it via bug-setup."})
        return 2
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    wb.emit({"ok": all(item["ok"] for item in results), "results": results})
    return 0 if all(item["ok"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
