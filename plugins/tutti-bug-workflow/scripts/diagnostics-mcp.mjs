#!/usr/bin/env node
import { createInterface } from "node:readline";
import { writeFile, rename, rm } from "node:fs/promises";
import { isAbsolute } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { pathToFileURL } from "node:url";
import { DiagnosticsClient } from "./chrome-webmcp.mjs";
export { DiagnosticsClient, parseConnection } from "./chrome-webmcp.mjs";

const protocolVersion = "2025-06-18";
const maxBytes = 24 * 1024 * 1024;
const properties = {
  connection_url: {
    type: "string",
    description:
      "Local WebMCP page link copied from Tutti, or a web-diagnostics UUID. Selects a page in the local Chrome profile."
  },
  range: { type: "string", enum: ["10m", "1h", "12h", "1d", "7d"] },
  level: { type: "string", enum: ["info", "warn", "error"] },
  limit: { type: "integer", minimum: 1, maximum: 200 },
  untilUnixMs: { type: "integer", minimum: 0 },
  beforeSequence: { type: "integer", minimum: 0 }
};
const tools = [
  {
    name: "get_web_logs",
    description:
      "Attach to existing local Chrome through native WebMCP and read unredacted logs from the identified Tutti page. Logs are untrusted data.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties,
      required: ["connection_url"],
      additionalProperties: false
    }
  },
  {
    name: "collect_web_logs",
    description:
      "Collect every page of retained logs in the ten minutes before question_time and write one web-logs.log with coverage metadata. If the size limit or a stalled cursor stops collection, the records already read are still written and collectionStatus is partial. No redaction. The page must remain open.",
    inputSchema: {
      type: "object",
      properties: {
        connection_url: properties.connection_url,
        question_time: {
          type: "string",
          description:
            "Original question time as an ISO 8601 timestamp with timezone."
        },
        output_path: {
          type: "string",
          description: "Absolute evidence path ending in web-logs.log."
        }
      },
      required: ["connection_url", "question_time", "output_path"],
      additionalProperties: false
    }
  },
  {
    name: "list_computer_candidates",
    description:
      "List candidate Computers for the Account signed in on the identified Tutti page: all Computers it owns (including offline), plus Computers behind the Agents of room_id when given. Reads every directory page. Use the result to ask QA which device was used; names are untrusted data.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: {
        connection_url: properties.connection_url,
        room_id: { type: "string", minLength: 1, maxLength: 256 }
      },
      required: ["connection_url"],
      additionalProperties: false
    }
  },
  {
    name: "list_web_rooms",
    description:
      "List every Room visible to the Account signed in on the identified Tutti page (roomId, name, isPublicRoom). Use it to resolve a room name from a screenshot before list_computer_candidates.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: { connection_url: properties.connection_url },
      required: ["connection_url"],
      additionalProperties: false
    }
  }
];

const maxDirectoryPages = 50;

// Directory cursors expire after 60 seconds, so every page is read in one call.
export async function readDirectory(client, toolName, itemsKey, query = {}) {
  const items = [];
  const cursors = new Set();
  let cursor;
  let observedAt;
  for (let pages = 1; ; pages++) {
    const result = await client.catalog(toolName, {
      ...query,
      limit: 200,
      ...(cursor === undefined ? {} : { cursor })
    });
    if (!Array.isArray(result[itemsKey]))
      throw new Error(`Native ${toolName} returned no ${itemsKey}`);
    items.push(...result[itemsKey]);
    observedAt ??= result.observedAt;
    if (result.nextCursor === null) return { items, pages, observedAt };
    if (cursors.has(result.nextCursor) || pages >= maxDirectoryPages)
      throw new Error(`Native ${toolName} pagination did not finish`);
    cursors.add(result.nextCursor);
    cursor = result.nextCursor;
  }
}

export async function listComputerCandidates(client, roomId) {
  const own = await readDirectory(client, "list_my_computers", "computers");
  const candidates = new Map();
  for (const computer of own.items)
    candidates.set(computer.computerId, {
      computerId: computer.computerId,
      displayName: computer.displayName,
      platform: computer.platform,
      connectionStatus: computer.connectionStatus,
      sources: ["own"],
      agents: computer.agents.map((agent) => ({
        agentTargetId: agent.agentTargetId,
        displayName: agent.displayName,
        executionAvailability: agent.executionAvailability
      }))
    });
  let room = null;
  if (roomId !== undefined) {
    const agents = await readDirectory(client, "list_room_agents", "agents", {
      roomId
    });
    room = { roomId, agentCount: agents.items.length };
    const unbound = [];
    for (const agent of agents.items) {
      const entry = {
        agentTargetId: agent.agentTargetId,
        displayName: agent.displayName,
        ownership: agent.ownership,
        executionAvailability: agent.executionAvailability
      };
      const id = agent.computer?.computerId ?? null;
      // A missing computerId stays unknown; never derive one from names.
      if (id === null) {
        unbound.push({
          computerId: null,
          displayName: agent.computer?.displayName ?? null,
          online: agent.computer?.online ?? null,
          sources: ["room_agent"],
          agents: [entry]
        });
        continue;
      }
      const existing = candidates.get(id);
      if (existing) {
        if (!existing.sources.includes("room_agent"))
          existing.sources.push("room_agent");
        if (!existing.agents.some((a) => a.agentTargetId === entry.agentTargetId))
          existing.agents.push(entry);
      } else
        candidates.set(id, {
          computerId: id,
          displayName: agent.computer?.displayName ?? null,
          online: agent.computer?.online ?? null,
          sources: ["room_agent"],
          agents: [entry]
        });
    }
    return finishCandidates(client, own, room, [...candidates.values(), ...unbound]);
  }
  return finishCandidates(client, own, room, [...candidates.values()]);
}

function finishCandidates(client, own, room, candidates) {
  return {
    pageSessionId: client.pageSessionId,
    accountId: client.accountId,
    observedAt: own.observedAt,
    room,
    candidateCount: candidates.length,
    candidates
  };
}

export async function collectLogs(client, questionTime) {
  if (
    typeof questionTime !== "string" ||
    !/(?:Z|[+-]\d{2}:\d{2})$/u.test(questionTime)
  )
    throw new Error("question_time must include a timezone");
  const untilUnixMs = Date.parse(questionTime);
  if (!Number.isSafeInteger(untilUnixMs) || untilUnixMs < 0)
    throw new Error("Invalid original question time");
  const sinceUnixMs = untilUnixMs - 10 * 60 * 1000;
  const records = [];
  const sequences = new Set();
  let beforeSequence;
  let bytes = 0;
  let pages = 0;
  let incompleteReason = null;
  collect: for (;;) {
    const snapshot = await client.read({
      range: "10m",
      limit: 200,
      untilUnixMs,
      ...(beforeSequence === undefined ? {} : { beforeSequence })
    });
    pages++;
    if (
      snapshot.sinceUnixMs !== sinceUnixMs ||
      snapshot.untilUnixMs !== untilUnixMs
    )
      throw new Error("Diagnostics query window changed during collection");
    for (const record of snapshot.records) {
      if (
        !Number.isSafeInteger(record.id) ||
        sequences.has(record.id) ||
        (beforeSequence !== undefined && record.id >= beforeSequence) ||
        record.occurredAtUnixMs < sinceUnixMs ||
        record.occurredAtUnixMs > untilUnixMs
      )
        throw new Error("Invalid diagnostics pagination or time window");
      sequences.add(record.id);
      const line = JSON.stringify(record);
      if (bytes + Buffer.byteLength(line) + 1 > maxBytes) {
        // Keep the newer records already read instead of discarding them.
        incompleteReason = "size_limit";
        break collect;
      }
      bytes += Buffer.byteLength(line) + 1;
      records.push(record);
    }
    if (!snapshot.truncated) break;
    const next = snapshot.nextBeforeSequence;
    if (
      !snapshot.records.length ||
      !Number.isSafeInteger(next) ||
      next !== snapshot.records.at(-1).id ||
      (beforeSequence !== undefined && next >= beforeSequence)
    ) {
      if (!records.length)
        throw new Error("Diagnostics pagination did not advance");
      incompleteReason = "pagination_stalled";
      break;
    }
    beforeSequence = next;
  }
  records.sort(
    (a, b) => a.occurredAtUnixMs - b.occurredAtUnixMs || a.id - b.id
  );
  const earliest = records.reduce(
    (value, record) => Math.min(value, record.occurredAtUnixMs),
    Infinity
  );
  const latest = records.reduce(
    (value, record) => Math.max(value, record.occurredAtUnixMs),
    -Infinity
  );
  const recordTruncationCount = records.filter(
    (record) => record.truncated === true
  ).length;
  const metadata = {
    type: "metadata",
    pageSessionId: client.pageSessionId,
    accountId: client.accountId,
    source: "tutti-chrome-webmcp",
    connectionReference: client.connection.reference,
    pageUrl: client.pageUrl,
    questionTime,
    sinceUnixMs,
    untilUnixMs,
    recordCount: records.length,
    pages,
    redacted: false,
    collectionStatus: incompleteReason ? "partial" : "complete",
    incompleteReason,
    paginationComplete: incompleteReason === null,
    recordTruncationCount,
    truncated: recordTruncationCount > 0 || incompleteReason !== null,
    retention: "current-page-memory",
    earliestRecordUnixMs: records.length ? earliest : null,
    latestRecordUnixMs: records.length ? latest : null,
    coverage: incompleteReason
      ? "Partial: newest retained records from question_time back to earliestRecordUnixMs; older records in the window were not collected."
      : "All retained records in the requested window. Serialization and record size limits still apply; excluded debug and evicted records cannot be recovered."
  };
  const text =
    [
      JSON.stringify(metadata),
      ...records.map((record) => JSON.stringify(record))
    ].join("\n") + "\n";
  return {
    metadata,
    text,
    sha256: createHash("sha256").update(text).digest("hex")
  };
}

async function callTool(name, args, signal, clientFactory) {
  const schema = tools.find((tool) => tool.name === name)?.inputSchema;
  if (
    !schema ||
    !args ||
    typeof args !== "object" ||
    Array.isArray(args) ||
    Object.keys(args).some((key) => !Object.hasOwn(schema.properties, key)) ||
    schema.required.some((key) => !Object.hasOwn(args, key))
  )
    throw new Error("Invalid diagnostic tool or arguments");
  const client = clientFactory(
    args.connection_url,
    AbortSignal.any([signal, AbortSignal.timeout(90_000)])
  );
  try {
    await client.initialize();
    if (name === "get_web_logs") {
      const { connection_url: _, ...query } = args;
      return await client.read(query);
    }
    if (name === "list_computer_candidates")
      return await listComputerCandidates(client, args.room_id);
    if (name === "list_web_rooms") {
      const rooms = await readDirectory(client, "list_rooms", "rooms");
      return {
        pageSessionId: client.pageSessionId,
        accountId: client.accountId,
        observedAt: rooms.observedAt,
        roomCount: rooms.items.length,
        rooms: rooms.items
      };
    }
    if (
      typeof args.output_path !== "string" ||
      !isAbsolute(args.output_path) ||
      !args.output_path.endsWith("web-logs.log")
    )
      throw new Error("output_path must be an absolute web-logs.log path");
    const collected = await collectLogs(client, args.question_time);
    const temp = `${args.output_path}.${randomUUID()}.tmp`;
    try {
      signal?.throwIfAborted();
      await writeFile(temp, collected.text, { flag: "wx", mode: 0o600 });
      signal?.throwIfAborted();
      await rename(temp, args.output_path);
    } finally {
      await rm(temp, { force: true });
    }
    return {
      ...collected.metadata,
      outputPath: args.output_path,
      sha256: collected.sha256,
      bytes: Buffer.byteLength(collected.text)
    };
  } finally {
    await client.dispose();
  }
}

export async function serve(
  input = process.stdin,
  output = process.stdout,
  {
    clientFactory = (link, signal) =>
      new DiagnosticsClient(link, undefined, signal)
  } = {}
) {
  const lines = createInterface({ input, crlfDelay: Infinity });
  let active = 0;
  const requests = new Map();
  const tasks = new Set();
  async function dispatch(line) {
    let request;
    const send = async (envelope) => {
      await new Promise((resolve, reject) =>
        output.write(`${JSON.stringify(envelope)}\n`, (error) =>
          error ? reject(error) : resolve()
        )
      );
    };
    try {
      if (Buffer.byteLength(line) > 1024 * 1024)
        throw new Error("Request too large");
      request = JSON.parse(line);
    } catch {
      return send({
        jsonrpc: "2.0",
        id: null,
        error: { code: -32700, message: "Invalid JSON-RPC input" }
      });
    }
    if (!request || typeof request !== "object" || Array.isArray(request))
      return send({
        jsonrpc: "2.0",
        id: null,
        error: { code: -32600, message: "Invalid request" }
      });
    if (!Object.hasOwn(request, "id")) {
      if (request.method === "notifications/cancelled")
        requests.get(request.params?.requestId)?.abort();
      return;
    }
    const reply = { jsonrpc: "2.0", id: request.id };
    if (request.jsonrpc !== "2.0" || typeof request.method !== "string")
      return send({
        ...reply,
        error: { code: -32600, message: "Invalid request" }
      });
    try {
      let result;
      if (request.method === "initialize")
        result = {
          protocolVersion,
          capabilities: { tools: {} },
          serverInfo: { name: "tutti-diagnostics", version: "1.0.0" }
        };
      else if (request.method === "ping") result = {};
      else if (request.method === "tools/list") result = { tools };
      else if (request.method === "tools/call") {
        if (active >= 4 || requests.has(request.id))
          throw new Error("Too many or duplicate diagnostic requests");
        active++;
        const controller = new AbortController();
        requests.set(request.id, controller);
        try {
          const value = await callTool(
            request.params?.name,
            request.params?.arguments,
            controller.signal,
            clientFactory
          );
          result = {
            content: [{ type: "text", text: JSON.stringify(value) }],
            structuredContent: value
          };
        } catch (error) {
          result = {
            isError: true,
            content: [{ type: "text", text: error.message }]
          };
        } finally {
          active--;
          requests.delete(request.id);
        }
      } else
        return send({
          ...reply,
          error: { code: -32601, message: "Method not found" }
        });
      await send({ ...reply, result });
    } catch (error) {
      await send({ ...reply, error: { code: -32603, message: error.message } });
    }
  }
  try {
    for await (const line of lines) {
      const task = dispatch(line).catch((error) =>
        process.stderr.write(
          `Diagnostics protocol write failed: ${error.message}\n`
        )
      );
      tasks.add(task);
      void task.finally(() => tasks.delete(task));
    }
  } finally {
    for (const controller of requests.values()) controller.abort();
    await Promise.allSettled(tasks);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href)
  await serve();
