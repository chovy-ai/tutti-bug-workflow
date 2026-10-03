"""Exercise persistent cache updates with real Git and local synthetic remotes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/sync_code.py"


@unittest.skipUnless(shutil.which("git"), "Git is required for cache integration checks")
class CodeCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.data = self.base / "data"
        self.data.mkdir()
        self.origin = self.base / "origin"
        self.origin.mkdir()
        self.git(self.origin, "init", "-b", "main")
        self.git(self.origin, "config", "user.name", "Cache Test")
        self.git(self.origin, "config", "user.email", "cache-test@example.invalid")
        self.first_sha = self.commit("initial")
        self.config = {"schema_version": 1, "repositories": [
            {"name": "client", "url": str(self.origin), "base_branch": "main"}], "cli_dependencies": []}
        self.save_config()

    def git(self, directory, *arguments):
        result = subprocess.run(["git", "-C", str(directory), *arguments],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, text):
        (self.origin / "case.txt").write_text(text)
        self.git(self.origin, "add", "case.txt")
        self.git(self.origin, "commit", "-m", text)
        return self.git(self.origin, "rev-parse", "HEAD")

    def save_config(self):
        (self.data / "config.json").write_text(json.dumps(self.config))

    def sync(self, expected=0, env=None):
        result = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", str(self.data)],
                                capture_output=True, text=True, env=env, timeout=25)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_reuses_cache_and_pins_existing_bug_when_main_advances(self):
        first = self.sync()["repositories"][0]
        cache = Path(first["cache_path"])
        self.assertTrue(first["created"])
        self.assertEqual(first["sha"], self.first_sha)
        worktree = self.base / "bug-worktree"
        self.git(cache, "worktree", "add", "-b", "codex/cache-test", str(worktree), first["sha"])
        (worktree / "case.txt").write_text("investigation notes")
        second_sha = self.commit("main advanced")
        second = self.sync()["repositories"][0]
        self.assertFalse(second["created"])
        self.assertEqual(second["cache_path"], first["cache_path"])
        self.assertEqual(second["sha"], second_sha)
        self.assertEqual(self.git(cache, "rev-parse", first["snapshot_ref"]), self.first_sha)
        self.assertEqual(self.git(worktree, "rev-parse", "HEAD"), self.first_sha)
        self.assertEqual((worktree / "case.txt").read_text(), "investigation notes")

    def test_local_seed_is_independent_and_excludes_uncommitted_files(self):
        seed = self.base / "seed"
        subprocess.run(["git", "clone", str(self.origin), str(seed)],capture_output=True,check=True)
        (seed / "case.txt").write_text("QA local changes")
        self.config["repositories"][0]["local_path"] = str(seed)
        self.save_config()
        first = self.sync()["repositories"][0]
        cache = Path(first["cache_path"])
        self.assertEqual(first["seeded_from"], str(seed))
        self.assertFalse((cache / "objects/info/alternates").exists())
        self.assertEqual(self.git(cache, "show", first["sha"] + ":case.txt"), "initial")
        self.assertEqual((seed / "case.txt").read_text(), "QA local changes")
        shutil.rmtree(seed)
        self.assertEqual(self.sync()["repositories"][0]["sha"], self.first_sha)

    def test_existing_cache_with_different_origin_is_preserved(self):
        first = self.sync()["repositories"][0]
        cache = Path(first["cache_path"])
        self.git(cache, "remote", "set-url", "origin", str(self.base / "different-origin"))
        failed = self.sync(expected=2)
        self.assertFalse(failed["ok"])
        self.assertEqual(self.git(cache, "rev-parse", first["snapshot_ref"]), self.first_sha)
        self.assertEqual(self.git(cache, "remote", "get-url", "origin"), str(self.base / "different-origin"))

    def test_failed_fetch_does_not_claim_cached_main_is_latest(self):
        first = self.sync()["repositories"][0]
        self.origin.rename(self.base / "origin-offline")
        failed = self.sync(expected=2)
        self.assertFalse(failed["latest_main_confirmed_for_all"])
        self.assertEqual(self.git(Path(first["cache_path"]), "rev-parse", first["snapshot_ref"]), self.first_sha)

    def test_rejects_cache_paths_outside_data_directory(self):
        self.config["repositories"][0]["cache_path"] = str(self.base / "outside.git")
        self.save_config()
        self.sync(expected=2)
        self.assertFalse((self.base / "outside.git").exists())

    def test_inherited_git_directory_cannot_redirect_cache_writes(self):
        report = self.sync(env=dict(os.environ, GIT_DIR=str(self.origin / ".git")))
        self.assertTrue(report["ok"])
        self.assertEqual(self.git(self.origin, "remote"), "")


if __name__ == "__main__":
    unittest.main()
