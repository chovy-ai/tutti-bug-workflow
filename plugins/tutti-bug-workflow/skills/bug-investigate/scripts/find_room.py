#!/usr/bin/env python3
"""Pick the Room a bug is filed in, from what the QA said: a Room ID, a Room/Task link,
a Room name, or a person's name (Rooms are usually named after their owner).

Reads the logged-in account's Room directory with `tutti-cli room list --json` (or
--rooms-file for tests). IDs and links must match a Room in the directory. Names are
matched case-insensitively against Room names, local Rooms first and cloud Rooms only
when no local Room matches; an exact name beats a partial match.

Output: one JSON result, status `matched` (room), `ambiguous` (candidates to ask the QA
about) or `not_found` (local_rooms to offer). Exit 2 when the directory can't be read.
Standard library only.
"""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import emit  # noqa: E402

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
ROOM_LINK = re.compile(r"/room/([0-9a-f-]{36})", re.I)
MAX_CANDIDATES = 20


def directory(rooms_file):
    if rooms_file:
        text = Path(rooms_file).read_text(encoding="utf-8")
    else:
        result = subprocess.run(["tutti-cli", "room", "list", "--json"],
                                capture_output=True, text=True, timeout=60, check=False)
        if result.returncode:
            raise ValueError((result.stderr or result.stdout).strip()[-300:] or "tutti-cli room list failed")
        text = result.stdout
    rooms = json.loads(text)["rooms"]
    if not isinstance(rooms, list):
        raise ValueError("room list returned no rooms array")
    return rooms


def resolve(query, rooms):
    text = query.strip()
    link = ROOM_LINK.search(text)
    wanted = (link.group(1) if link else text if UUID.fullmatch(text) else "").lower()
    if wanted:
        room = next((r for r in rooms if r["id"].lower() == wanted), None)
        if room:
            return {"status": "matched", "by": "id", "room": room}
        return {"status": "not_found", "by": "id", "reason": "该账号的房间列表里没有这个 Room ID"}
    needle = text.casefold()
    for kind in ("local", "cloud"):
        pool = [r for r in rooms if r.get("type") == kind]
        exact = [r for r in pool if r["name"].strip().casefold() == needle]
        partial = exact or [r for r in pool if needle in r["name"].casefold()]
        if len(partial) == 1:
            return {"status": "matched", "by": "name", "room": partial[0]}
        if partial:
            return {"status": "ambiguous", "by": "name", "candidates": partial[:MAX_CANDIDATES],
                    "candidate_count": len(partial)}
    return {"status": "not_found", "by": "name"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", required=True, help="Room ID, Room/Task link, Room name or person name.")
    parser.add_argument("--rooms-file", help="Saved `tutti-cli room list --json` output (tests).")
    args = parser.parse_args()
    try:
        rooms = directory(args.rooms_file)
    except (ValueError, OSError, KeyError, subprocess.TimeoutExpired) as error:
        emit({"ok": False, "error": str(error)})
        return 2
    result = resolve(args.query, rooms)
    if result["status"] == "not_found":
        local = [r for r in rooms if r.get("type") == "local"]
        result.update(local_rooms=local[:MAX_CANDIDATES], local_room_count=len(local))
    emit({"ok": True, "query": args.query, **result})
    return 0


if __name__ == "__main__":
    sys.exit(main())
