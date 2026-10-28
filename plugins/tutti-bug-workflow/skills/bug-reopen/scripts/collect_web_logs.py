#!/usr/bin/env python3
"""Collect WebMCP logs inside a local process; stdout contains metadata only."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

from merge_web_logs import merge, parse_link, snapshot_of, window_of


class ChromeMcp:
    def __init__(self, stderr, deadline):
        config = json.loads((Path(__file__).resolve().parents[3] / "mcp.json").read_text())
        server = config["mcpServers"]["chrome-devtools"]
        self.deadline, self.sequence = deadline, 0
        command = server["command"]
        if os.name == "nt" and command == "npx":
            command = "npx.cmd"
        self.process = subprocess.Popen(
            [command, *server["args"], "--experimentalStructuredContent", "--pageIdRouting",
             "--no-usage-statistics", "--no-performance-crux"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
            start_new_session=os.name != "nt")
        self.replies = queue.Queue()
        self.reader = threading.Thread(target=self.read_replies)
        self.reader.start()

    def read_replies(self):
        try:
            while True:
                line = self.process.stdout.readline(16 * 1024 * 1024 + 1)
                if not line:
                    raise RuntimeError("chrome_mcp_disconnected")
                if len(line) > 16 * 1024 * 1024:
                    raise RuntimeError("chrome_mcp_response_too_large")
                self.replies.put(json.loads(line))
        except (ValueError, OSError, RuntimeError) as error:
            self.replies.put(error)

    def send(self, message):
        self.process.stdin.write((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())
        self.process.stdin.flush()

    def rpc(self, method, params):
        self.sequence += 1
        self.send({"id": self.sequence, "method": method, "params": params})
        deadline = min(self.deadline, time.monotonic() + 35)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("chrome_mcp_timeout")
            try:
                reply = self.replies.get(timeout=remaining)
            except queue.Empty as error:
                raise RuntimeError("chrome_mcp_timeout") from error
            if isinstance(reply, Exception):
                raise RuntimeError("chrome_mcp_invalid_response") from reply
            if reply.get("id") != self.sequence:
                continue
            if reply.get("jsonrpc") != "2.0" or "error" in reply or "result" not in reply:
                raise RuntimeError("chrome_mcp_request_failed")
            return reply["result"]

    def initialize(self):
        self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "tutti-web-log-collector", "version": "1.0.0"}})
        self.send({"method": "notifications/initialized"})

    def call(self, name, arguments):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError") or not isinstance(result.get("structuredContent"), dict):
            raise RuntimeError("chrome_mcp_tool_failed")
        return result["structuredContent"]

    def close(self):
        try:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
            if os.name == "nt":
                if self.process.poll() is None:
                    self.process.terminate()
            else:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    self.process.kill()
                else:
                    os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        finally:
            self.reader.join(timeout=2)
            if self.reader.is_alive() and os.name != "nt":
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self.reader.join()
            self.process.stdout.close()


def descriptor(client, page_id):
    tools = client.call("list_webmcp_tools", {"pageId": page_id}).get("webmcpTools", [])
    matches = [tool for tool in tools if tool.get("name") == "get_web_logs"]
    if len(matches) != 1:
        return None
    tool = matches[0]
    page = re.search(r"Page identity: ([^;]+);", tool.get("description", ""))
    account = re.search(r"Account identity: ([^;]+);", tool.get("description", ""))
    if not page or not account or tool.get("annotations", {}).get("readOnlyHint") is not True:
        raise RuntimeError("webmcp_identity_unavailable")
    return page[1], account[1]


def atomic_write(path, text):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def collect(args, client):
    page_identity, account = parse_link(args.connection_url)
    if args.account_id:
        if account and account != args.account_id:
            raise ValueError("account_identity_mismatch")
        account = args.account_id
    if not account:
        raise ValueError("account_identity_required")
    _, until, range_name, _ = window_of(args.question_time, args.incident_at)
    client.initialize()
    pages = client.call("list_pages", {}).get("pages", [])
    matches = [page for page in pages if descriptor(client, page["id"]) == (page_identity, account)]
    if len(matches) != 1:
        raise RuntimeError("webmcp_page_not_unique")
    page_id = matches[0]["id"]
    collected, before, interruption = [], None, None
    while True:
        try:
            if descriptor(client, page_id) != (page_identity, account):
                raise RuntimeError("webmcp_identity_changed")
            query = {"range": range_name, "limit": 200, "untilUnixMs": until}
            if before is not None:
                query["beforeSequence"] = before
            raw = client.call("execute_webmcp_tool", {"pageId": page_id, "toolName": "get_web_logs",
                                                     "input": json.dumps(query)})
            snapshot = snapshot_of(raw)
            if (snapshot.get("pageSessionId"), snapshot.get("accountId")) != (page_identity, account):
                raise RuntimeError("webmcp_identity_changed")
            if descriptor(client, page_id) != (page_identity, account):
                raise RuntimeError("webmcp_identity_changed")
            collected.append(raw)
            atomic_write(args.output.parent / f"page-{len(collected)}.json", json.dumps(raw, ensure_ascii=False))
            if not snapshot.get("truncated"):
                break
            next_before = snapshot.get("nextBeforeSequence")
            if not snapshot["records"] or next_before != snapshot["records"][-1]["id"] or (before is not None and next_before >= before):
                interruption = "webmcp_cursor_stalled"
                break
            before = next_before
        except (RuntimeError, OSError, ValueError, KeyError, StopIteration) as error:
            interruption = str(error) if isinstance(error, RuntimeError) else "webmcp_collection_failed"
            break
    if not collected:
        raise RuntimeError(interruption or "webmcp_collection_empty")
    metadata, records = merge(collected, page_identity, account, args.question_time, args.incident_at)
    if interruption:
        metadata.update(collectionStatus="partial", errorCode=interruption)
    text = "\n".join(json.dumps(item, ensure_ascii=False) for item in [metadata, *records]) + "\n"
    atomic_write(args.output, text)
    return {**metadata, "path": str(args.output), "bytes": len(text.encode()),
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connection-url", required=True)
    parser.add_argument("--account-id")
    parser.add_argument("--question-time", required=True)
    parser.add_argument("--incident-at")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    args.output = args.output.expanduser().resolve()
    if args.output.name != "web-logs.log" or args.timeout <= 0:
        parser.error("--output must end in web-logs.log and --timeout must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    client = None
    def interrupt(_number, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    try:
        with (args.output.parent / "chrome-mcp.stderr.log").open("ab") as stderr:
            client = ChromeMcp(stderr, time.monotonic() + args.timeout)
            result = collect(args, client)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0 if result["collectionStatus"] == "complete" else 1
    except (KeyboardInterrupt, ValueError, OSError, RuntimeError, KeyError) as error:
        code = str(error) if isinstance(error, RuntimeError) else "webmcp_collection_failed"
        print(json.dumps({"ok": False, "errorCode": code,
                          "stderrPath": str(args.output.parent / "chrome-mcp.stderr.log")}))
        return 2
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
