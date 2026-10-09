import { spawn } from "node:child_process";

const protocolVersion = "2025-06-18";
const pagePattern =
  /^web-diagnostics:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/u;
const nativeMethods = new Set([
  "list_pages",
  "list_webmcp_tools",
  "execute_webmcp_tool"
]);

export function parseConnection(value) {
  if (typeof value !== "string" || value.length > 2048)
    throw new Error(
      "A copied Tutti WebMCP page link or diagnostic ID is required"
    );
  if (pagePattern.test(value))
    return { reference: value, pageSessionId: value };
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("Invalid local WebMCP page reference");
  }
  const pageSessionId = decodeURIComponent(url.pathname.slice(1));
  const accountId = url.searchParams.get("accountId");
  if (
    url.protocol !== "tutti-webmcp:" ||
    url.host !== "page" ||
    url.username ||
    url.password ||
    url.hash ||
    !pagePattern.test(pageSessionId) ||
    !accountId ||
    accountId.length > 256 ||
    [...url.searchParams.keys()].some((key) => key !== "accountId") ||
    url.searchParams.getAll("accountId").length !== 1
  )
    throw new Error("Invalid local WebMCP page reference");
  return { reference: value, pageSessionId, accountId };
}

function isTuttiPage(value) {
  try {
    const url = new URL(value);
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    const extra = (process.env.TUTTI_WEBMCP_ALLOWED_ORIGINS ?? "")
      .split(",")
      .filter(Boolean);
    return (
      (url.protocol === "https:" || (local && url.protocol === "http:")) &&
      (["tutti.sh", "api.tutti.sh"].includes(url.hostname) ||
        local ||
        extra.includes(url.origin)) &&
      (url.pathname === "/platform" || url.pathname.startsWith("/platform/"))
    );
  } catch {
    return false;
  }
}

// This child belongs to one request. It attaches to the user's existing Chrome;
// it never starts Chrome, selects/focuses a tab, evaluates scripts or clicks UI.
export class ChromeMcpPeer {
  constructor({
    command = process.platform === "win32" ? "npx.cmd" : "npx",
    args = [
      "-y",
      "chrome-devtools-mcp@1.10.1",
      "--autoConnect",
      "--categoryExperimentalWebmcp",
      "--experimentalStructuredContent",
      "--pageIdRouting",
      "--no-usage-statistics",
      "--no-performance-crux",
      "--no-category-input",
      "--no-category-emulation",
      "--no-category-performance",
      "--no-category-network",
      "--no-category-debugging",
      "--no-category-memory"
    ]
  } = {}) {
    this.nextID = 0;
    this.pending = new Map();
    this.buffer = "";
    this.closed = false;
    this.child = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
      detached: process.platform !== "win32",
      shell: process.platform === "win32" && command.endsWith(".cmd")
    });
    this.exited = new Promise((resolve) => this.child.once("close", resolve));
    this.child.on("error", (error) =>
      this.fail(new Error(`Chrome MCP could not start: ${error.message}`))
    );
    this.child.stdin.on("error", (error) => this.fail(error));
    this.child.once("close", () =>
      this.fail(
        new Error(
          "Chrome MCP disconnected; check Chrome remote-debugging permission"
        )
      )
    );
    this.child.stderr.on("data", () => {}); // Drain upstream diagnostics; never mix them with MCP stdout.
    this.child.stdout.setEncoding("utf8");
    this.child.stdout.on("data", (text) => {
      this.buffer += text;
      if (Buffer.byteLength(this.buffer) > 4 * 1024 * 1024) {
        this.fail(new Error("Chrome MCP response exceeds the size limit"));
        return;
      }
      for (;;) {
        const end = this.buffer.indexOf("\n");
        if (end < 0) break;
        const line = this.buffer.slice(0, end);
        this.buffer = this.buffer.slice(end + 1);
        let reply;
        try {
          reply = JSON.parse(line);
        } catch {
          this.fail(new Error("Chrome MCP returned invalid JSON-RPC"));
          return;
        }
        if (!Object.hasOwn(reply, "id")) continue;
        const pending = this.pending.get(reply.id);
        if (!pending) continue;
        if (
          reply.jsonrpc !== "2.0" ||
          (!reply.error && !Object.hasOwn(reply, "result"))
        )
          pending.reject(new Error("Invalid Chrome MCP response"));
        else if (reply.error)
          pending.reject(
            new Error(
              `Chrome MCP error ${reply.error.code}: ${reply.error.message}`
            )
          );
        else pending.resolve(reply.result);
      }
    });
  }

  fail(error) {
    this.failure = error;
    for (const pending of [...this.pending.values()]) pending.reject(error);
  }

  rpc(method, params, signal) {
    signal?.throwIfAborted();
    if (this.failure) return Promise.reject(this.failure);
    if (this.closed) return Promise.reject(new Error("Chrome MCP is closed"));
    const id = ++this.nextID;
    return new Promise((resolve, reject) => {
      const finish = (callback, value) => {
        clearTimeout(timer);
        signal?.removeEventListener("abort", abort);
        this.pending.delete(id);
        callback(value);
      };
      const abort = () =>
        finish(
          reject,
          signal.reason ?? new Error("Chrome MCP request cancelled")
        );
      const timer = setTimeout(
        () =>
          finish(
            reject,
            new Error(
              "Chrome MCP timed out; enable remote debugging and allow the Chrome connection"
            )
          ),
        35_000
      );
      this.pending.set(id, {
        resolve: (value) => finish(resolve, value),
        reject: (error) => finish(reject, error)
      });
      signal?.addEventListener("abort", abort, { once: true });
      this.child.stdin.write(
        JSON.stringify({
          jsonrpc: "2.0",
          id,
          method,
          ...(params ? { params } : {})
        }) + "\n",
        (error) => {
          if (error) this.pending.get(id)?.reject(error);
        }
      );
    });
  }

  async initialize(signal) {
    const result = await this.rpc(
      "initialize",
      {
        protocolVersion,
        capabilities: {},
        clientInfo: { name: "tutti-diagnostics", version: "0.1.38" }
      },
      signal
    );
    if (
      result.protocolVersion !== protocolVersion ||
      !result.capabilities?.tools
    )
      throw new Error("Chrome MCP protocol is unsupported");
    this.child.stdin.write(
      JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) +
        "\n"
    );
    const listed = await this.rpc("tools/list", {}, signal);
    for (const name of nativeMethods) {
      const tool = listed.tools?.find((item) => item.name === name);
      if (
        !tool ||
        (name !== "list_pages" &&
          !tool.inputSchema?.required?.includes("pageId"))
      )
        throw new Error(
          "Chrome MCP needs native WebMCP tools and explicit pageId routing"
        );
    }
  }

  async call(name, args, signal) {
    if (!nativeMethods.has(name))
      throw new Error(
        "Only native Chrome WebMCP discovery and execution are allowed"
      );
    const result = await this.rpc(
      "tools/call",
      { name, arguments: args },
      signal
    );
    if (result.isError)
      throw new Error(
        result.content?.find((item) => item.type === "text")?.text ??
          "Chrome WebMCP call failed"
      );
    if (!result.structuredContent)
      throw new Error("Chrome MCP structured content is required");
    return result.structuredContent;
  }

  async dispose() {
    if (this.closed) return this.exited;
    this.closed = true;
    this.fail(new Error("Chrome MCP request finished"));
    const stop = (signal) => {
      if (this.child.exitCode !== null || this.child.signalCode !== null)
        return;
      try {
        if (process.platform === "win32") this.child.kill(signal);
        else if (this.child.pid) process.kill(-this.child.pid, signal);
      } catch (error) {
        if (error.code !== "ESRCH") throw error;
      }
    };
    stop("SIGTERM");
    const timer = setTimeout(() => stop("SIGKILL"), 1000);
    try {
      await this.exited;
    } finally {
      clearTimeout(timer);
    }
  }
}

export class DiagnosticsClient {
  constructor(link, peer, signal) {
    this.connection = parseConnection(link);
    this.peer = peer ?? new ChromeMcpPeer();
    this.signal = signal;
    this.pageSessionId = this.connection.pageSessionId;
    this.accountId = this.connection.accountId;
  }

  async pages() {
    const result = await this.peer.call("list_pages", {}, this.signal);
    if (!Array.isArray(result.pages))
      throw new Error("Chrome MCP did not return open pages");
    return result.pages.filter(
      (page) => Number.isSafeInteger(page.id) && isTuttiPage(page.url)
    );
  }

  async descriptor(pageId) {
    const result = await this.peer.call(
      "list_webmcp_tools",
      { pageId },
      this.signal
    );
    if (!Array.isArray(result.webmcpTools))
      throw new Error(
        "Native Chrome WebMCP is unavailable; enable the WebMCP browser feature"
      );
    const logs = result.webmcpTools.filter(
      (tool) => tool.name === "get_web_logs"
    );
    if (logs.length > 1) throw new Error("Ambiguous native get_web_logs tools");
    const tool = logs[0];
    if (!tool) return null;
    const page = /Page identity: (web-diagnostics:[0-9a-f-]{36});/u.exec(
      tool.description ?? ""
    )?.[1];
    const account = /Account identity: ([^;]+);/u.exec(
      tool.description ?? ""
    )?.[1];
    return { tool, page, account };
  }

  async initialize() {
    await this.peer.initialize(this.signal);
    const matches = [];
    for (const page of await this.pages()) {
      const descriptor = await this.descriptor(page.id);
      if (descriptor?.page === this.pageSessionId)
        matches.push({ page, descriptor });
    }
    if (matches.length !== 1)
      throw new Error(
        matches.length
          ? "Page identity is ambiguous in Chrome"
          : "The copied Tutti page is not open in this Chrome profile"
      );
    const { page, descriptor } = matches[0];
    this.pageId = page.id;
    this.pageUrl = page.url;
    this.verify(descriptor);
    this.accountId = descriptor.account;
  }

  verify(descriptor) {
    if (
      !descriptor ||
      descriptor.page !== this.pageSessionId ||
      !descriptor.account ||
      (this.accountId && descriptor.account !== this.accountId) ||
      descriptor.tool.annotations?.readOnlyHint !== true ||
      !descriptor.tool.inputSchema?.properties?.beforeSequence
    )
      throw new Error(
        "The page/Account changed or native unredacted pagination is unavailable; copy a fresh link from the updated page"
      );
  }

  async read(query = {}) {
    if (!(await this.pages()).some((page) => page.id === this.pageId))
      throw new Error("The Tutti page closed or navigated away");
    this.verify(await this.descriptor(this.pageId));
    const response = await this.peer.call(
      "execute_webmcp_tool",
      {
        pageId: this.pageId,
        toolName: "get_web_logs",
        input: JSON.stringify(query)
      },
      this.signal
    );
    let execution;
    try {
      execution = JSON.parse(response.message);
    } catch {
      throw new Error("Invalid Chrome WebMCP execution result");
    }
    if (execution.status !== "Completed" || execution.errorText)
      throw new Error(
        execution.errorText || `Chrome WebMCP execution ${execution.status}`
      );
    let snapshot = execution.output;
    if (typeof snapshot === "string") {
      try {
        snapshot = JSON.parse(snapshot);
      } catch {
        throw new Error("Invalid native page log snapshot");
      }
    }
    if (
      !snapshot ||
      snapshot.pageSessionId !== this.pageSessionId ||
      snapshot.accountId !== this.accountId ||
      snapshot.redacted !== false ||
      !Array.isArray(snapshot.records) ||
      !Number.isSafeInteger(snapshot.sinceUnixMs) ||
      !Number.isSafeInteger(snapshot.untilUnixMs) ||
      typeof snapshot.truncated !== "boolean"
    )
      throw new Error(
        "Native page/Account identity or log snapshot contract changed"
      );
    for (const record of snapshot.records) {
      if (
        record.pageSessionId !== this.pageSessionId ||
        record.userId !== this.accountId
      )
        throw new Error("Native WebMCP returned an unrelated page or Account");
    }
    return snapshot;
  }

  dispose() {
    return this.peer.dispose();
  }
}
