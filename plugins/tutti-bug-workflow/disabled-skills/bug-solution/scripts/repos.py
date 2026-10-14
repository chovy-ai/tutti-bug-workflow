#!/usr/bin/env python3
"""Keep the global analysis checkouts of each repository on the latest remote main.

Each repository has a bare cache (`cache_path`) and one global, read-only checkout
(`checkout_path`, a detached worktree of the cache) in the data directory. `sync`
fetches main into the cache and moves the checkout to it. All bugs share the same
checkout; root-cause analysis only reads it. Fixes never happen here: bug-execute
cuts its own worktree from remote main.
"""

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as wb  # noqa: E402


def git(directory, *arguments):
    environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"):
        environment.pop(key, None)
    result = subprocess.run(["git", "-C", str(directory), *arguments],
                            capture_output=True, text=True, env=environment, timeout=600)
    if result.returncode:
        raise ValueError(f"git {arguments[0]} failed in {directory}: {result.stderr.strip()}")
    return result.stdout.strip()


@contextmanager
def repositories_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (root / ".sync.lock").open("a+b") as stream:
        deadline = time.monotonic() + 60
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ValueError("Repositories are being updated by another run; retry shortly.")
                time.sleep(0.2)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def canonical_url(url):
    return url.rstrip("/").removesuffix(".git")


def inside(root, value, default):
    path = Path(value or default).expanduser()
    path = (path if path.is_absolute() else root / path).resolve()
    if root not in path.parents:
        raise ValueError(f"{path} must be inside the data directory {root}.")
    return path


def repositories(cfg, root, names=None):
    items = cfg.get("repositories")
    if not isinstance(items, list) or not items:
        raise ValueError("Configure repositories before synchronising code.")
    result = []
    for item in items:
        name, url, branch = (item.get(key) for key in ("name", "url", "base_branch"))
        if not isinstance(name, str) or not wb.NAME.fullmatch(name):
            raise ValueError(f"Invalid repository name: {name!r}.")
        if not url or not branch or str(url).startswith("-") or str(branch).startswith("-"):
            raise ValueError(f"Configure a real url and base_branch for {name}.")
        if names and name not in names:
            continue
        result.append({"name": name, "url": url, "branch": branch,
                       "cache": inside(root, item.get("cache_path"), f"repositories/{name}.git"),
                       "checkout": inside(root, item.get("checkout_path"), f"repositories/{name}")})
    unknown = set(names or []) - {item["name"] for item in result}
    if unknown:
        raise ValueError(f"Unknown repositories: {sorted(unknown)}.")
    return result


def fetch(repo):
    """Create the bare cache if needed, fetch main, and return the remote-tracking ref and SHA."""
    cache = repo["cache"]
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{repo['name']}-init-", dir=cache.parent))
        try:
            git(temporary, "init", "--bare")
            git(temporary, "remote", "add", "origin", repo["url"])
            temporary.rename(cache)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    if git(cache, "rev-parse", "--is-bare-repository") != "true" or \
            canonical_url(git(cache, "remote", "get-url", "origin")) != canonical_url(repo["url"]):
        raise ValueError(f"{cache} is not a bare cache of {repo['url']}; leave it intact.")
    reference = f"refs/remotes/origin/{repo['branch']}"
    git(cache, "fetch", "--no-tags", "--prune", "origin", f"+refs/heads/{repo['branch']}:{reference}")
    git(cache, "worktree", "prune")
    return reference, git(cache, "rev-parse", "--verify", f"{reference}^{{commit}}")


def sync_checkout(repo):
    reference, sha = fetch(repo)
    checkout = repo["checkout"]
    if not checkout.exists():
        git(repo["cache"], "worktree", "add", "--detach", str(checkout), sha)
    else:
        if git(checkout, "status", "--porcelain"):
            raise ValueError(f"{checkout} has local changes; the analysis checkout is read-only. "
                             "Move those changes away, then re-run.")
        git(checkout, "checkout", "--detach", sha)
    head = git(checkout, "rev-parse", "HEAD")
    if head != sha:
        raise ValueError(f"{checkout} is at {head}, expected {sha}.")
    return {"name": repo["name"], "branch": repo["branch"], "sha": sha, "checkout": str(checkout),
            "commit_time": git(checkout, "log", "-1", "--format=%cI")}


def main():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    command = commands.add_parser("sync", help="Fetch main and move the global checkouts to it.")
    command.add_argument("--data-dir")
    command.add_argument("--config")
    command.add_argument("--repo", action="append", help="Repository name; default all.")
    args = result.parse_args()
    try:
        if not shutil.which("git"):
            raise ValueError("git is required.")
        root = wb.data_root(args)
        repos = repositories(wb.load_config(args, root), root, args.repo)
        with repositories_lock(root / "repositories"):
            wb.emit({"ok": True, "repositories": [sync_checkout(repo) for repo in repos]})
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
