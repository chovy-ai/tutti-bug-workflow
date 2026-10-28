#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
page="web-diagnostics:95eafceb-4246-4616-b8ca-15bcbb8eff14"
scenario=os.environ.get("CHROME_FIXTURE_SCENARIO", "complete")
Path(os.environ["CHROME_FIXTURE_PID"]).write_text(str(os.getpid()))
print("fixture diagnostic contains PRIVATE-LOG-CONTENT", file=sys.stderr, flush=True)
count=0
for line in sys.stdin:
 req=json.loads(line)
 if "id" not in req: continue
 method=req["method"]
 if method=="initialize":result={"protocolVersion":"2025-06-18","capabilities":{"tools":{}}}
 else:
  name=req["params"]["name"]
  if name=="list_pages":result={"pages":[{"id":1,"url":"https://tutti.sh/platform/room/room"}]}
  elif name=="list_webmcp_tools":result={"webmcpTools":[{"name":"get_web_logs","description":f"Page identity: {page}; Account identity: user-a;","annotations":{"readOnlyHint":True}}]}
  else:
   count+=1
   if scenario=="partial" and count==2:
    sys.stdin.read();break
   query=json.loads(req["params"]["arguments"]["input"])
   until=query["untilUnixMs"]
   account="user-b" if scenario=="identity" else "user-a"
   record={"id":3 if count==1 else 2,"occurredAtUnixMs":until-count*1000,"pageSessionId":page,"userId":account,"event":"PRIVATE-LOG-CONTENT"}
   snapshot={"pageSessionId":page,"accountId":account,"sinceUnixMs":until-600000,"untilUnixMs":until,"redacted":False,"records":[record],"truncated":count==1,"nextBeforeSequence":99 if scenario=="stalled" else record["id"]}
   result={"message":json.dumps({"status":"Completed","output":json.dumps(snapshot)})}
  result={"structuredContent":result}
 print(json.dumps({"jsonrpc":"2.0","id":req["id"],"result":result}),flush=True)
