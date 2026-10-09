"""Dossier consistency checks for this skill; synthetic data, no external services."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dossier.py"


class DossierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.data = self.base / "data"

    def run_cli(self, operation, *arguments, expected=0):
        command = [sys.executable, str(SCRIPT), operation, "--data-dir", str(self.data), *arguments]
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def approved_fixture(self):
        """Simulated approval tests consistency only; this is not a real RD approval."""
        self.run_cli("new-bug", "--bug-id", "BUG-001")
        directory = self.data / "bugs/BUG-001"
        bug = json.loads((directory / "bug.json").read_text())
        bug.update({"status": "waiting_rd_approval", "baselines": {"web": "a" * 40, "server": "b" * 40},
                    "root_cause": {"version": 1, "status": "confirmed", "input_revision": 1},
                    "plan": {"version": 2, "status": "approved", "root_cause_version": 1},
                    "acceptance": {"version": 1, "plan_version": 2}})
        (directory / "bug.json").write_text(json.dumps(bug))
        for name, contents in {"analysis.md": "Confirmed synthetic cause", "plan.md": "Synthetic plan v2",
                               "acceptance.md": "Synthetic behavior assertions"}.items():
            (directory / name).write_text(contents)
        hashes = self.run_cli("artifact-hashes", "--bug-id", "BUG-001")["artifact_sha256"]
        approval = {"bug_id": "BUG-001", "decision": "approved", "input_revision": 1,
                    "root_cause_version": 1, "plan_version": 2, "acceptance_version": 1,
                    "baselines": bug["baselines"], "artifact_sha256": hashes,
                    "actor": {"id": "test-only-rd", "role": "RD"},
                    "approved_at": "2026-09-30T12:00:00+00:00",
                    "source": {"kind": "codex_user_message", "reference": "synthetic-fixture"}}
        (directory / "approval.json").write_text(json.dumps(approval))
        return directory

    def test_dossier_preserves_existing_work_and_contains_paths(self):
        self.run_cli("new-bug", "--bug-id", "BUG-001")
        analysis = self.data / "bugs/BUG-001/analysis.md"
        analysis.write_text("QA analysis already completed")
        self.assertEqual(self.run_cli("new-bug", "--bug-id", "BUG-001")["action"], "preserved")
        self.assertEqual(analysis.read_text(), "QA analysis already completed")
        self.run_cli("new-bug", "--bug-id", "../escaped", expected=2)
        self.assertFalse((self.data / "escaped").exists())

    def test_unapproved_bug_is_blocked(self):
        self.run_cli("new-bug", "--bug-id", "BUG-001")
        report = self.run_cli("check-execution", "--bug-id", "BUG-001", expected=2)
        self.assertFalse(report["consistent"])
        self.assertTrue(any("approval receipt" in error for error in report["errors"]))

    def test_consistent_fixture_still_requires_identity_verification(self):
        self.approved_fixture()
        report = self.run_cli("check-execution", "--bug-id", "BUG-001")
        self.assertTrue(report["consistent"])
        self.assertFalse(report["approval_identity_verified"])

    def test_edited_plan_invalidates_prior_approval(self):
        directory = self.approved_fixture()
        (directory / "plan.md").write_text("Different plan with unchanged version number")
        report = self.run_cli("check-execution", "--bug-id", "BUG-001", expected=2)
        self.assertTrue(any("Reports changed" in error for error in report["errors"]))

    def test_new_qa_input_and_code_drift_invalidate_prior_approval(self):
        directory = self.approved_fixture()
        bug = json.loads((directory / "bug.json").read_text())
        bug["input_revision"] = 2
        bug["baselines"]["server"] = "c" * 40
        (directory / "bug.json").write_text(json.dumps(bug))
        report = self.run_cli("check-execution", "--bug-id", "BUG-001", expected=2)
        self.assertTrue(any("latest QA input" in error for error in report["errors"]))
        self.assertTrue(any("stale: baselines" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
