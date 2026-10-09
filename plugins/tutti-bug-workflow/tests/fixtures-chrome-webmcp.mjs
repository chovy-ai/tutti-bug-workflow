import { createInterface } from "node:readline";
const pageSessionId = "web-diagnostics:95eafceb-4246-4616-b8ca-15bcbb8eff14";
const mode = process.argv[2];
let reads = 0;
let catalogCalls = 0;
const catalogDescriptors = ["list_my_computers", "list_rooms", "list_room_agents"].map(
  (name) => ({
    name,
    description: `Directory. Page identity: ${pageSessionId}. Default limit 50.`,
    annotations: { readOnlyHint: true }
  })
);
const computerPages = [
  [
    {
      computerId: "c-1",
      displayName: "QA MacBook",
      platform: "darwin",
      connectionStatus: "online",
      agents: [{ agentTargetId: "a-1", displayName: "Codex", executionAvailability: { status: "available" } }]
    }
  ],
  [
    {
      computerId: "c-2",
      displayName: "Office PC",
      platform: "windows",
      connectionStatus: "offline",
      agents: []
    }
  ]
];
function catalog(toolName, query) {
  catalogCalls++;
  const base = { pageSessionId, observedAt: "2026-10-09T00:00:00.000Z" };
  if (mode === "stale-cursor") return { ...base, computers: [], nextCursor: "same" };
  if (toolName === "list_my_computers") {
    const index = query.cursor === "next" ? 1 : 0;
    return { ...base, computers: computerPages[index], nextCursor: index ? null : "next" };
  }
  if (toolName === "list_rooms")
    return { ...base, rooms: [{ roomId: "r-1", name: "Bug room", isPublicRoom: false }], nextCursor: null };
  return {
    ...base,
    roomId: query.roomId,
    agents: [
      { agentTargetId: "a-1", displayName: "Codex", ownership: "self", executionAvailability: { status: "available" }, computer: { computerId: "c-1", displayName: "QA MacBook", online: true } },
      { agentTargetId: "a-9", displayName: "Shared Claude", ownership: "shared", executionAvailability: { status: "available" }, computer: { computerId: "c-9", displayName: "Teammate Mini", online: false } },
      { agentTargetId: "a-0", displayName: "Hidden", ownership: "requestable", executionAvailability: { status: "unavailable" }, computer: { computerId: null, displayName: null, online: false } }
    ],
    nextCursor: null
  };
}
const descriptor = {
  name: "get_web_logs",
  description: `Page identity: ${pageSessionId}; Account identity: user-a;`,
  annotations: { readOnlyHint: true },
  inputSchema: {
    type: "object",
    properties: { beforeSequence: { type: "integer" } }
  }
};
for await (const line of createInterface({ input: process.stdin })) {
  const request = JSON.parse(line);
  if (!Object.hasOwn(request, "id")) continue;
  let result;
  if (request.method === "initialize")
    result = { protocolVersion: "2025-06-18", capabilities: { tools: {} } };
  else if (request.method === "tools/list")
    result = {
      tools: ["list_pages", "list_webmcp_tools", "execute_webmcp_tool"].map(
        (name) => ({
          name,
          inputSchema: { required: name === "list_pages" ? [] : ["pageId"] }
        })
      )
    };
  else {
    const { name, arguments: args } = request.params;
    if (name === "list_pages")
      result = {
        pages: [
          {
            id: 7,
            url:
              mode === "navigate" && reads
                ? "https://example.com/platform"
                : "https://tutti.sh/platform/chat/a"
          },
          { id: 8, url: "https://tutti.sh/platform/chat/b" },
          { id: 9, url: "https://example.com/platform" },
          ...(mode === "duplicate"
            ? [{ id: 10, url: "https://tutti.sh/platform/chat/c" }]
            : [])
        ]
      };
    else if (name === "list_webmcp_tools") {
      const account =
        mode === "catalog-switch" && catalogCalls ? "user-b" : "user-a";
      result = {
        webmcpTools:
          args.pageId === 8
            ? []
            : [
                {
                  ...descriptor,
                  description: `Page identity: ${pageSessionId}; Account identity: ${account};`
                },
                ...(mode === "no-catalog" ? [] : catalogDescriptors)
              ]
      };
    } else if (
      name === "execute_webmcp_tool" &&
      args.pageId === 7 &&
      args.toolName !== "get_web_logs"
    )
      result = {
        message: JSON.stringify({
          status: "Completed",
          output: JSON.stringify(catalog(args.toolName, JSON.parse(args.input)))
        })
      };
    else if (
      name === "execute_webmcp_tool" &&
      args.pageId === 7 &&
      args.toolName === "get_web_logs"
    ) {
      if (mode === "hang") continue;
      const query = JSON.parse(args.input);
      reads++;
      const accountId = mode === "switch" && reads > 1 ? "user-b" : "user-a";
      const id = query.beforeSequence === undefined ? 2 : 1;
      const output = {
        accountId,
        pageSessionId,
        redacted: false,
        sinceUnixMs: query.untilUnixMs - 600000,
        untilUnixMs: query.untilUnixMs,
        truncated: id === 2,
        nextBeforeSequence: id === 2 ? 2 : undefined,
        records:
          mode === "empty-switch"
            ? []
            : [
                {
                  id,
                  userId: accountId,
                  pageSessionId,
                  occurredAtUnixMs: query.untilUnixMs - id * 1000,
                  details: { token: "RAW_SECRET", url: "?token=RAW" },
                  truncated: id === 1
                }
              ]
      };
      if (mode === "empty-switch") output.accountId = "user-b";
      result = { message: JSON.stringify({ status: "Completed", output }) };
    } else throw new Error("Unexpected method or wrong page: " + name);
    result = { structuredContent: result, content: [] };
  }
  process.stdout.write(
    JSON.stringify({ jsonrpc: "2.0", id: request.id, result }) + "\n"
  );
}
