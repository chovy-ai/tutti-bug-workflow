import { createInterface } from "node:readline";
const pageSessionId = "web-diagnostics:95eafceb-4246-4616-b8ca-15bcbb8eff14";
const mode = process.argv[2];
let reads = 0;
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
    else if (name === "list_webmcp_tools")
      result = { webmcpTools: args.pageId === 8 ? [] : [descriptor] };
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
