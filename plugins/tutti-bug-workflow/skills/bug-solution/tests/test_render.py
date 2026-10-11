"""Mermaid sources render to checked PNGs through a fake mmdc."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/render.py"


class RenderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.env = {**os.environ, "MMDC": str(ROOT / "tests/fixtures-mmdc.py"),
                    "BUG_WORKBENCH_DATA": str(self.base / "data")}

    def render(self, *names, expected=0):
        arguments = []
        for name in names:
            arguments += ["--input", str(self.base / name)]
        result = subprocess.run([sys.executable, str(SCRIPT), *arguments, "--output-dir", str(self.base / "png")],
                                capture_output=True, text=True, timeout=30, env=self.env, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_renders_each_source_and_reports_size(self):
        (self.base / "flow.mmd").write_text("flowchart TD\n  A --> B")
        (self.base / "arch.mmd").write_text("flowchart LR\n  Web --> Server")
        report = self.render("flow.mmd", "arch.mmd")
        self.assertTrue(report["ok"])
        self.assertEqual([(r["width"], r["height"]) for r in report["results"]], [(640, 480), (640, 480)])
        self.assertTrue((self.base / "png/arch.png").is_file())

    def test_syntax_errors_are_reported_per_file(self):
        (self.base / "flow.mmd").write_text("flowchart TD\n  A --> B")
        (self.base / "bad.mmd").write_text("flowchart TD\n  syntax error")
        report = self.render("flow.mmd", "bad.mmd", expected=1)
        self.assertEqual([r["ok"] for r in report["results"]], [True, False])
        self.assertIn("Parse error", report["results"][1]["error"])
        self.assertFalse((self.base / "png/bad.png").exists())


if __name__ == "__main__":
    unittest.main()
