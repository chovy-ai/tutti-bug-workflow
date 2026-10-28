import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/"scripts/collect_web_logs.py"
LINK="tutti-webmcp://page/web-diagnostics:95eafceb-4246-4616-b8ca-15bcbb8eff14?accountId=user-a"
class CollectWebLogsTests(unittest.TestCase):
 def run_collector(self,scenario):
  temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
  base=Path(temporary.name);binary=base/"npx"
  binary.write_text(f"#!{sys.executable}\n"+(Path(__file__).parent/"fixtures-chrome-webmcp.py").read_text())
  binary.chmod(0o700)
  env={**os.environ,"PATH":str(base)+os.pathsep+os.environ["PATH"],"CHROME_FIXTURE_SCENARIO":scenario,"CHROME_FIXTURE_PID":str(base/"pid")}
  result=subprocess.run([sys.executable,str(SCRIPT),"--connection-url",LINK,"--question-time","2026-10-08T23:00:00Z","--output",str(base/"logs/web-logs.log"),"--timeout","5" if scenario=="partial" else "30"],env=env,capture_output=True,text=True,timeout=40)
  self.assertNotIn("PRIVATE-LOG-CONTENT",result.stdout+result.stderr)
  if (base/"pid").exists():
   with self.assertRaises(ProcessLookupError):os.kill(int((base/"pid").read_text()),0)
  return result,json.loads(result.stdout),base
 def test_complete_collection_writes_pages_without_returning_records(self):
  result,data,base=self.run_collector("complete")
  self.assertEqual(result.returncode,0,result.stdout)
  self.assertEqual((data["pages"],data["recordCount"],data["collectionStatus"]),(2,2,"complete"))
  self.assertNotIn("records",data)
  self.assertIn("PRIVATE-LOG-CONTENT",(base/"logs/web-logs.log").read_text())
  self.assertTrue((base/"logs/page-2.json").is_file())
 def test_timeout_preserves_valid_partial_collection_and_joins_child(self):
  result,data,base=self.run_collector("partial")
  self.assertEqual(result.returncode,1,result.stdout)
  self.assertEqual((data["collectionStatus"],data["recordCount"]),("partial",1))
  self.assertEqual(data["errorCode"],"chrome_mcp_timeout")
 def test_changed_identity_is_rejected_before_any_log_file(self):
  result,data,base=self.run_collector("identity")
  self.assertEqual(result.returncode,2,result.stdout)
  self.assertFalse((base/"logs/web-logs.log").exists())
  self.assertFalse((base/"logs/page-1.json").exists())
 def test_stalled_cursor_is_explicitly_partial(self):
  result,data,base=self.run_collector("stalled")
  self.assertEqual(result.returncode,1,result.stdout)
  self.assertEqual(data["collectionStatus"],"partial")
