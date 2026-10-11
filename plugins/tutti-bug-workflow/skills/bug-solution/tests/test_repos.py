"""Global analysis checkouts follow the remote main of a local test repository."""

import json
import os
from pathlib import Path
import shutil
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
        self.work = self.base / "work"
        git(self.base, "clone", "-q", str(self.remote), str(self.work))
        git(self.work, "config", "user.email", "t@example.com")
        git(self.work, "config", "user.name", "t")
        self.commit("one")
        self.data = self.base / "data"
        self.data.mkdir()
        cfg = json.loads(EXAMPLE_CONFIG.read_text())
        cfg["repositories"] = [{"name": "tutti", "url": str(self.remote), "base_branch": "main",
                                "cache_path": "repositories/tutti.git", "checkout_path": "repositories/tutti"}]
        (self.data / "config.json").write_text(json.dumps(cfg))

    def commit(self, text):
        (self.work / "file.txt").write_text(text)
        git(self.work, "add", ".")
        git(self.work, "commit", "-qm", text)
        git(self.work, "push", "-q", "origin", "HEAD:main")
        return git(self.work, "rev-parse", "HEAD")

    def sync(self, expected=0):
        result = subprocess.run([sys.executable, str(SCRIPT), "sync", "--data-dir", str(self.data)],
                                capture_output=True, text=True, timeout=60, check=False,
                                env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"})
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_sync_creates_then_moves_the_global_checkout(self):
        first = self.sync()["repositories"][0]
        checkout = self.data / "repositories/tutti"
        self.assertEqual((first["sha"], first["checkout"]), (git(self.work, "rev-parse", "HEAD"), str(checkout)))
        self.assertEqual((checkout / "file.txt").read_text(), "one")
        second_sha = self.commit("two")
        second = self.sync()["repositories"][0]
        self.assertEqual(second["sha"], second_sha)
        self.assertEqual((checkout / "file.txt").read_text(), "two")

    def test_local_edits_in_the_checkout_block_sync(self):
        self.sync()
        (self.data / "repositories/tutti/file.txt").write_text("edited")
        self.commit("two")
        self.assertIn("read-only", self.sync(expected=2)["error"])
        self.assertEqual((self.data / "repositories/tutti/file.txt").read_text(), "edited")


if __name__ == "__main__":
    unittest.main()
