#!/usr/bin/env python3
"""Update persistent bare Git caches and return pinned main snapshots."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from workbench import NAME, data_root, emit, load_config, read_json, write_json

MARKER = "bug-workbench-cache.json"


def git(directory, *arguments):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        environment.pop(key, None)
    result = subprocess.run(["git", "-C", str(directory), *arguments],
                            capture_output=True, text=True, env=environment, timeout=300)
    if result.returncode:
        raise ValueError(f"Git {arguments[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


@contextmanager
def cache_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".sync.lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if not stream.tell():
                stream.write(b"0")
                stream.flush()
            def lock():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            def unlock():
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            def lock():
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            def unlock():
                fcntl.flock(stream, fcntl.LOCK_UN)
        deadline = time.monotonic() + 30
        while True:
            try:
                lock()
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError("Code cache is being updated; retry after that update completes.")
                time.sleep(0.1)
        try:
            yield
        finally:
            unlock()


def canonical_url(url):
    return url.rstrip("/").removesuffix(".git")


def repository_specs(cfg, root):
    repositories = cfg.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise ValueError("Configure the repositories before synchronizing code.")
    seen_names, seen_paths = set(), set()
    result = []
    for item in repositories:
        if not isinstance(item, dict):
            raise ValueError("Each repository must be an object.")
        name, url, branch = (item.get(key) for key in ("name", "url", "base_branch"))
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in seen_names:
            raise ValueError("Repository names must be valid and unique.")
        if (not isinstance(url, str) or not url or url.startswith("-")
                or not isinstance(branch, str) or not branch or branch.startswith("-")):
            raise ValueError(f"Configure a real remote and branch for {name}.")
        git(root, "check-ref-format", f"refs/heads/{branch}")
        selected = Path(item.get("cache_path") or f"repositories/{name}.git").expanduser()
        path = (selected if selected.is_absolute() else root / selected).resolve()
        if root not in path.parents or path in seen_paths:
            raise ValueError("Code cache paths must be distinct and inside the data directory.")
        seen_names.add(name)
        seen_paths.add(path)
        result.append((item, path))
    return result


def seed_cache(cache, item):
    selected = item.get("local_path")
    if not selected:
        return None
    source = Path(selected).expanduser().resolve()
    if not source.is_dir():
        return None
    try:
        remote = git(source, "remote", "get-url", "origin")
        if canonical_url(remote) != canonical_url(item["url"]):
            return None
        reference = f"refs/remotes/origin/{item['base_branch']}"
        git(source, "rev-parse", "--verify", f"{reference}^{{commit}}")
    except ValueError:
        return None
    git(cache, "fetch", "--no-tags", str(source),
        f"+{reference}:refs/remotes/origin/{item['base_branch']}")
    return str(source)


def synchronize_repository(item, path, run_id):
    path.parent.mkdir(parents=True, exist_ok=True)
    created = not path.exists()
    temporary = None
    if created:
        temporary = Path(tempfile.mkdtemp(prefix=f".{item['name']}-init-", dir=path.parent))
        cache = temporary
    else:
        cache = path
    try:
        if created:
            git(cache, "init", "--bare")
            git(cache, "remote", "add", "origin", item["url"])
            seeded_from = seed_cache(cache, item)
        else:
            marker = read_json(cache / MARKER)
            if (marker.get("name") != item["name"]
                    or canonical_url(marker.get("url", "")) != canonical_url(item["url"])
                    or git(cache, "rev-parse", "--is-bare-repository") != "true"
                    or canonical_url(git(cache, "remote", "get-url", "origin")) != canonical_url(item["url"])):
                raise ValueError(f"Existing cache identity differs for {item['name']}; leave it intact.")
            seeded_from = marker.get("seeded_from")
        reference = f"refs/remotes/origin/{item['base_branch']}"
        git(cache, "fetch", "--no-tags", "origin", f"+refs/heads/{item['base_branch']}:{reference}")
        sha = git(cache, "rev-parse", "--verify", f"{reference}^{{commit}}")
        snapshot_ref = f"refs/tutti-bug-workflow/snapshots/{run_id}"
        git(cache, "update-ref", snapshot_ref, sha)
        report = {"name": item["name"], "url": item["url"], "base_branch": item["base_branch"],
                  "cache_path": str(path), "sha": sha, "snapshot_ref": snapshot_ref,
                  "fetched_at": datetime.now(timezone.utc).isoformat(),
                  "created": created, "seeded_from": seeded_from}
        write_json(cache / MARKER, report)
        if created:
            cache.rename(path)
        return report
    finally:
        if temporary and temporary.exists():
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir")
    parser.add_argument("--config")
    args = parser.parse_args()
    try:
        if not shutil.which("git"):
            raise ValueError("Git is required.")
        root = data_root(args)
        cfg = load_config(args, root)
        root.mkdir(parents=True, exist_ok=True)
        specs = repository_specs(cfg, root)
        run_id = "sync-" + uuid.uuid4().hex
        with cache_lock(root / "repositories"):
            reports = [synchronize_repository(item, path, run_id) for item, path in specs]
            result = {"ok": True, "strategy": "shared-bare", "run_id": run_id, "repositories": reports}
            write_json(root / "repositories/sync-runs" / f"{run_id}.json", result)
        emit(result)
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        emit({"ok": False, "error": str(exc), "latest_main_confirmed_for_all": False})
        return 2


if __name__ == "__main__":
    sys.exit(main())
