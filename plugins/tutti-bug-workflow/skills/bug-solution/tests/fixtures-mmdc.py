#!/usr/bin/env python3
"""Fake mmdc: writes a tiny PNG, or fails like a Mermaid syntax error when the source says so."""

from pathlib import Path
import struct
import sys

args = sys.argv[1:]
source, target = Path(args[args.index("-i") + 1]), Path(args[args.index("-o") + 1])
if "syntax error" in source.read_text():
    print("Parse error on line 2", file=sys.stderr)
    sys.exit(1)
target.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 640, 480))
