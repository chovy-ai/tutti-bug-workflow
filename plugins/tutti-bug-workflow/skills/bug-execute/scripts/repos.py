#!/usr/bin/env python3
"""Per-fix worktrees cut from the remote branch, pushed, kept through the PPE deploy, then removed.

`start` fetches the base branch (`--base`, default the configured main) into the
repository's bare cache (`cache_path`) and adds a worktree on a new branch at
`worktrees/<repo>/<branch>` in the data directory, cut from the latest origin base; when the
branch already exists on origin (a retried fix) it is cut from that remote branch instead.
The base is remembered on the branch so `push` and `remove` compare against it. `push` requires a clean tree with new commits,
pushes the branch to origin and checks the remote now points at the local HEAD; the
worktree stays for the PR and the PPE deploy. `remove` detaches the worktree and the
local branch at the end; it refuses unpushed work unless `--discard` (failed or
abandoned fixes). Nothing else is kept: the pushed branch and its PR are the record.
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
        raise ValueError("Configure repositories before cutting a worktree.")
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
                       "cache": inside(root, item.get("cache_path"), f"repositories/{name}.git")})
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


def worktree_path(root, repo, branch):
    return root / "worktrees" / repo["name"] / branch.replace("/", "-")


def owner(root, repos, path):
    """Find the repository whose cache owns the worktree at path."""
    path = Path(path).expanduser().resolve()
    if root / "worktrees" not in path.parents:
        raise ValueError(f"{path} is not a worktree created by `start`.")
    common = Path(git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    repo = next((item for item in repos if item["cache"] == common), None)
    if not repo:
        raise ValueError(f"{path} does not belong to a configured repository cache.")
    return repo, path


def with_base(repo, path):
    """The repository as seen by the fix branch at path: its recorded base replaces main."""
    branch = git(path, "symbolic-ref", "--short", "HEAD")
    try:
        base = git(repo["cache"], "config", f"branch.{branch}.bugBase")
    except ValueError:
        base = ""
    return {**repo, "branch": base or repo["branch"]}, branch


def detach(repo, path, branch):
    git(repo["cache"], "worktree", "remove", str(path))
    git(repo["cache"], "branch", "-D", branch)


def start(args, root, repos):
    repo = repos[0]
    if args.base:
        if args.base.startswith("-"):
            raise ValueError(f"Invalid base branch {args.base!r}.")
        git(root, "check-ref-format", f"refs/heads/{args.base}")
        repo = {**repo, "branch": args.base}
    git(root, "check-ref-format", f"refs/heads/{args.branch}")
    if args.branch == repo["branch"]:
        raise ValueError(f"Cut a fix branch, not {repo['branch']}.")
    reference, sha = fetch(repo)
    if git(repo["cache"], "for-each-ref", f"refs/heads/{args.branch}"):
        raise ValueError(f"Branch {args.branch} already exists in the cache; remove its "
                         "worktree first, or pick another name.")
    path = worktree_path(root, repo, args.branch)
    if path.exists():
        raise ValueError(f"{path} already exists.")
    path.parent.mkdir(parents=True, exist_ok=True)
    resumed = bool(git(repo["cache"], "ls-remote", "--heads", "origin", args.branch))
    start_point = sha
    if resumed:
        # A retried fix continues the branch (and its PR) from the previous attempt.
        remote_ref = f"refs/remotes/origin/{args.branch}"
        git(repo["cache"], "fetch", "--no-tags", "origin", f"+refs/heads/{args.branch}:{remote_ref}")
        start_point = git(repo["cache"], "rev-parse", "--verify", f"{remote_ref}^{{commit}}")
    git(repo["cache"], "worktree", "add", "--no-track", "-b", args.branch, str(path), start_point)
    git(repo["cache"], "config", f"branch.{args.branch}.bugBase", repo["branch"])
    return {"repository": repo["name"], "branch": args.branch, "worktree": str(path), "resumed": resumed,
            "head": start_point, "base_branch": repo["branch"], "base_sha": sha,
            "behind_main": int(git(path, "rev-list", "--count", f"HEAD..{reference}")) if resumed else 0}


def push(args, root, repos):
    repo, path = owner(root, repos, args.path)
    repo, branch = with_base(repo, path)
    if git(path, "status", "--porcelain"):
        raise ValueError(f"{path} has uncommitted changes; commit them before pushing.")
    reference, base = fetch(repo)
    head = git(path, "rev-parse", "HEAD")
    if not git(path, "rev-list", f"{reference}..HEAD"):
        raise ValueError(f"{branch} has no commits beyond {repo['branch']}; nothing to push.")
    git(path, "push", "origin", f"HEAD:refs/heads/{branch}")
    remote = git(path, "ls-remote", "--heads", "origin", branch).split()
    if not remote or remote[0] != head:
        raise ValueError(f"origin/{branch} is not at {head} after push.")
    return {"repository": repo["name"], "branch": branch, "pushed_sha": head,
            "base_branch": repo["branch"], "main_sha": base, "url": repo["url"], "worktree": str(path)}


def remove(args, root, repos):
    repo, path = owner(root, repos, args.path)
    repo, branch = with_base(repo, path)
    if not args.discard:
        if git(path, "status", "--porcelain"):
            raise ValueError(f"{path} has uncommitted changes; pass --discard to drop them.")
        reference = f"refs/remotes/origin/{repo['branch']}"
        remote = git(path, "ls-remote", "--heads", "origin", branch).split()
        if git(path, "rev-list", f"{reference}..HEAD") and (
                not remote or remote[0] != git(path, "rev-parse", "HEAD")):
            raise ValueError(f"{branch} has unpushed commits; pass --discard to drop them.")
    if args.discard:
        git(repo["cache"], "worktree", "remove", "--force", str(path))
        git(repo["cache"], "branch", "-D", branch)
    else:
        detach(repo, path, branch)
    return {"repository": repo["name"], "branch": branch, "worktree_removed": str(path),
            "discarded": bool(args.discard)}


def main():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="operation", required=True)
    for name in ("start", "push", "remove"):
        command = commands.add_parser(name)
        command.add_argument("--data-dir")
        command.add_argument("--config")
        if name == "start":
            command.add_argument("--repo", required=True, help="Repository name from config.")
            command.add_argument("--branch", required=True, help="New fix branch, e.g. codex/room-name-sync.")
            command.add_argument("--base", help="Branch to cut from and open the PR against; default main. "
                                                "Use the feature branch when the bug is in unmerged work.")
        else:
            command.add_argument("--path", required=True, help="Worktree path returned by `start`.")
        if name == "remove":
            command.add_argument("--discard", action="store_true", help="Drop uncommitted/unpushed work.")
    args = result.parse_args()
    try:
        if not shutil.which("git"):
            raise ValueError("git is required.")
        root = wb.data_root(args)
        repos = repositories(wb.load_config(args, root), root,
                             [args.repo] if args.operation == "start" else None)
        with repositories_lock(root / "repositories"):
            report = {"start": start, "push": push, "remove": remove}[args.operation](args, root, repos)
        wb.emit({"ok": True, **report})
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        wb.emit({"ok": False, "error": str(error)})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
