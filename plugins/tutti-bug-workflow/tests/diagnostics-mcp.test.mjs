import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { PassThrough } from "node:stream";
import { createHash } from "node:crypto";
import {
  ChromeMcpPeer,
  DiagnosticsClient,
  parseConnection
} from "../scripts/chrome-webmcp.mjs";
import {
  collectLogs,
  listComputerCandidates,
  readDirectory,
  serve
} from "../scripts/diagnostics-mcp.mjs";
const id = "web-diagnostics:95eafceb-4246-4616-b8ca-15bcbb8eff14";
const link = `tutti-webmcp://page/${id}?accountId=user-a`;
const time = "2026-10-08T23:00:00Z";
function client(mode, signal, reference = link) {
  const peer = new ChromeMcpPeer({
    command: process.execPath,
    args: [
      fileURLToPath(new URL("./fixtures-chrome-webmcp.mjs", import.meta.url)),
      mode ?? "normal"
    ]
  });
  return new DiagnosticsClient(reference, peer, signal);
}
test("local reference and old page ID; HTTP endpoints and ambiguous account are rejected", () => {
  assert.equal(parseConnection(link).accountId, "user-a");
  assert.equal(parseConnection(id).pageSessionId, id);
  for (const value of [
    "https://tutti.sh/api/desktop/v2/web-diagnostics/connections/x/mcp#secret",
    link + "&accountId=user-b",
    link + "#secret",
    "web-diagnostics:invalid"
  ])
    assert.throws(() => new DiagnosticsClient(value));
});
test("official stdio protocol selects exact page and exports every raw page with fixed window", async () => {
  const c = client();
  try {
    await c.initialize();
    assert.equal(c.pageId, 7);
    const logs = await collectLogs(c, time);
    assert.equal(logs.metadata.pages, 2);
    assert.equal(logs.metadata.recordCount, 2);
    assert.equal(logs.metadata.accountId, "user-a");
    assert.equal(logs.metadata.source, "tutti-chrome-webmcp");
    assert.equal(logs.metadata.recordTruncationCount, 1);
    assert.equal(logs.metadata.truncated, true);
    assert.match(logs.text, /RAW_SECRET/);
    assert.match(logs.text, /\?token=RAW/);
    assert.equal(
      logs.sha256,
      createHash("sha256").update(logs.text).digest("hex")
    );
    await assert.rejects(c.peer.call("evaluate_script", {}), /Only native/);
  } finally {
    await c.dispose();
  }
  assert.equal(
    c.peer.child.exitCode !== null || c.peer.child.signalCode !== null,
    true
  );
});
for (const mode of ["switch", "empty-switch", "navigate", "duplicate"])
  test(`identity failures are explicit: ${mode}`, async () => {
    const c = client(mode);
    try {
      await assert.rejects(async () => {
        await c.initialize();
        await collectLogs(c, time);
      }, /identity|Account|navigated|ambiguous/);
    } finally {
      await c.dispose();
    }
  });
test("copied account must match native descriptor even with old page ID supported", async () => {
  const c = client(undefined, undefined, link.replace("user-a", "user-b"));
  try {
    await assert.rejects(c.initialize(), /Account/);
  } finally {
    await c.dispose();
  }
  const legacy = client(undefined, undefined, id);
  try {
    await legacy.initialize();
    assert.equal(legacy.accountId, "user-a");
  } finally {
    await legacy.dispose();
  }
});
test("cancellation rejects a pending native read and closes its owned process", async () => {
  const controller = new AbortController();
  const c = client("hang", controller.signal);
  try {
    await c.initialize();
    const read = c.read({ untilUnixMs: Date.parse(time) });
    setTimeout(() => controller.abort(new Error("cancelled test")), 25);
    await assert.rejects(read, /cancelled test/);
  } finally {
    await c.dispose();
  }
  assert.equal(c.peer.pending.size, 0);
});
test("plugin tools/call generates one attachment and returns its hash; EOF and shutdown are clean", async () => {
  const dir = await mkdtemp(join(tmpdir(), "tutti-native-test-"));
  const input = new PassThrough();
  const output = new PassThrough();
  const created = [];
  const responses = [];
  let buffer = "";
  const response = new Promise((resolve) =>
    output.on("data", (chunk) => {
      buffer += chunk;
      for (;;) {
        const end = buffer.indexOf("\n");
        if (end < 0) break;
        const value = JSON.parse(buffer.slice(0, end));
        buffer = buffer.slice(end + 1);
        responses.push(value);
        if (value.id === 2) resolve(value);
      }
    })
  );
  const running = serve(input, output, {
    clientFactory: (reference, signal) => {
      const c = client(undefined, signal, reference);
      created.push(c);
      return c;
    }
  });
  try {
    input.write(
      JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) + "\n"
    );
    input.write(
      JSON.stringify({
        jsonrpc: "2.0",
        id: 2,
        method: "tools/call",
        params: {
          name: "collect_web_logs",
          arguments: {
            connection_url: link,
            question_time: time,
            output_path: join(dir, "web-logs.log")
          }
        }
      }) + "\n"
    );
    const reply = await response;
    assert.equal(reply.result.isError, undefined);
    const text = await readFile(join(dir, "web-logs.log"), "utf8");
    assert.equal(
      reply.result.structuredContent.sha256,
      createHash("sha256").update(text).digest("hex")
    );
    assert.equal(text.trim().split("\n").length, 3);
    assert.equal(created[0].peer.closed, true);
    assert.deepEqual(
      responses[0].result.tools.map((tool) => tool.name),
      [
        "get_web_logs",
        "collect_web_logs",
        "list_computer_candidates",
        "list_web_rooms"
      ]
    );
  } finally {
    input.end();
    await running;
    await rm(dir, { recursive: true, force: true });
  }
});
test("input EOF cancels active native calls and waits for their cleanup", async () => {
  const input = new PassThrough();
  const output = new PassThrough();
  output.resume();
  let created;
  const running = serve(input, output, {
    clientFactory: (reference, signal) => {
      created = client("hang", signal, reference);
      return created;
    }
  });
  input.write(
    JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name: "get_web_logs", arguments: { connection_url: link } }
    }) + "\n"
  );
  input.end();
  await running;
  assert.equal(created.peer.closed, true);
  assert.equal(created.peer.pending.size, 0);
});
test("pagination rejects changed window or a non-advancing cursor", async () => {
  const until = Date.parse(time);
  await assert.rejects(
    collectLogs(
      {
        read: async () => ({
          sinceUnixMs: until - 1,
          untilUnixMs: until,
          records: []
        })
      },
      time
    ),
    /window changed/
  );
  await assert.rejects(
    collectLogs(
      {
        read: async () => ({
          sinceUnixMs: until - 600000,
          untilUnixMs: until,
          records: [],
          truncated: true,
          nextBeforeSequence: 1
        })
      },
      time
    ),
    /did not advance/
  );
});
test("records read before a stalled cursor are kept as partial", async () => {
  const until = Date.parse(time);
  let calls = 0;
  const logs = await collectLogs(
    {
      connection: { reference: link },
      read: async () => {
        calls++;
        return {
          sinceUnixMs: until - 600000,
          untilUnixMs: until,
          records:
            calls === 1 ? [{ id: 9, occurredAtUnixMs: until - 1000 }] : [],
          truncated: true,
          nextBeforeSequence: 9
        };
      }
    },
    time
  );
  assert.equal(logs.metadata.collectionStatus, "partial");
  assert.equal(logs.metadata.incompleteReason, "pagination_stalled");
  assert.equal(logs.metadata.paginationComplete, false);
  assert.equal(logs.metadata.truncated, true);
  assert.equal(logs.metadata.recordCount, 1);
});
test("computer candidates read every page and merge room agents without inventing IDs", async () => {
  const c = client();
  try {
    await c.initialize();
    const own = await listComputerCandidates(c);
    assert.deepEqual(
      own.candidates.map((item) => item.computerId),
      ["c-1", "c-2"]
    );
    assert.equal(own.accountId, "user-a");
    const withRoom = await listComputerCandidates(c, "r-1");
    const byId = new Map(withRoom.candidates.map((item) => [item.computerId, item]));
    assert.deepEqual(byId.get("c-1").sources, ["own", "room_agent"]);
    assert.equal(byId.get("c-1").agents.length, 1);
    assert.deepEqual(byId.get("c-9").sources, ["room_agent"]);
    assert.equal(byId.get(null).agents[0].agentTargetId, "a-0");
    assert.equal(withRoom.candidateCount, 4);
    const rooms = await readDirectory(c, "list_rooms", "rooms");
    assert.equal(rooms.items[0].roomId, "r-1");
  } finally {
    await c.dispose();
  }
});
for (const [mode, pattern] of [
  ["catalog-switch", /page\/Account changed/],
  ["no-catalog", /unavailable on this page/],
  ["stale-cursor", /pagination did not finish/]
])
  test(`directory failures are explicit: ${mode}`, async () => {
    const c = client(mode);
    try {
      await c.initialize();
      await assert.rejects(listComputerCandidates(c), pattern);
    } finally {
      await c.dispose();
    }
  });
