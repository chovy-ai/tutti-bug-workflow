"""Fix worktrees are cut from remote main, pushed, then removed."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/repos.py"
EXAMPLE_CONFIG = ROOT.parents[1] / "config/workbench.example.json"


def git(directory, *arguments):
    return subprocess.run(["git", "-C", str(directory), *arguments], capture_output=True, text=True,
                          check=True).stdout.strip()


class ReposTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.remote = self.base / "remote.git"
        git(self.base, "init", "--bare", "-b", "main", str(self.remote))
        work = self.base / "work"
        git(self.base, "clone", "-q", str(self.remote), str(work))
        self.identity(work)
        (work / "file.txt").write_text("one")
        git(work, "add", ".")
        git(work, "commit", "-qm", "one")
        git(work, "push", "-q", "origin", "HEAD:main")
        self.main = git(work, "rev-parse", "HEAD")
        self.data = self.base / "data"
        self.data.mkdir()
        cfg = json.loads(EXAMPLE_CONFIG.read_text())
        cfg["repositories"] = [{"name": "tutti", "url": str(self.remote), "base_branch": "main",
                                "cache_path": "repositories/tutti.git"}]
        (self.data / "config.json").write_text(json.dumps(cfg))

    @staticmethod
    def identity(directory):
        git(directory, "config", "user.email", "t@example.com")
        git(directory, "config", "user.name", "t")

    def run_script(self, *arguments, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), arguments[0], "--data-dir", str(self.data),
                                 *arguments[1:]], capture_output=True, text=True, timeout=60, check=False,
                                env=os.environ)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def start(self, branch="codex/room-name"):
        started = self.run_script("start", "--repo", "tutti", "--branch", branch)
        path = Path(started["worktree"])
        self.identity(path)
        return started, path

    def test_start_commit_push_keeps_the_worktree_until_removed(self):
        started, path = self.start()
        self.assertEqual((started["base_sha"], git(path, "rev-parse", "HEAD")), (self.main, self.main))
        self.assertFalse(started["resumed"])
        self.assertEqual(path, self.data / "worktrees/tutti/codex-room-name")
        self.assertIn("nothing to push", self.run_script("push", "--path", str(path), expected=2)["error"])
        (path / "file.txt").write_text("fixed")
        self.assertIn("uncommitted", self.run_script("push", "--path", str(path), expected=2)["error"])
        git(path, "commit", "-qam", "fix")
        head = git(path, "rev-parse", "HEAD")
        pushed = self.run_script("push", "--path", str(path))
        self.assertEqual((pushed["branch"], pushed["pushed_sha"]), ("codex/room-name", head))
        self.assertEqual(git(self.remote, "rev-parse", "refs/heads/codex/room-name"), head)
        self.assertTrue(path.exists())  # kept for the PR and the PPE deploy
        self.assertFalse(self.run_script("remove", "--path", str(path))["discarded"])
        self.assertFalse(path.exists())
        cache = self.data / "repositories/tutti.git"
        self.assertEqual(git(cache, "for-each-ref", "refs/heads/codex/room-name"), "")
        resumed, again = self.start()  # a retry continues the pushed branch
        self.assertEqual((resumed["resumed"], git(again, "rev-parse", "HEAD")), (True, head))

    def test_remove_refuses_unpushed_work_unless_discarded(self):
        _, path = self.start()
        (path / "file.txt").write_text("wip")
        git(path, "commit", "-qam", "wip")
        self.assertIn("unpushed", self.run_script("remove", "--path", str(path), expected=2)["error"])
        self.assertTrue(self.run_script("remove", "--path", str(path), "--discard")["discarded"])
        self.assertFalse(path.exists())
        self.start()  # the branch name is free again

    def test_only_worktrees_from_start_are_accepted(self):
        self.assertIn("not a worktree", self.run_script("push", "--path", str(self.base / "work"), expected=2)["error"])
        self.assertIn("Cut a fix branch",
                      self.run_script("start", "--repo", "tutti", "--branch", "main", expected=2)["error"])


if __name__ == "__main__":
    unittest.main()
