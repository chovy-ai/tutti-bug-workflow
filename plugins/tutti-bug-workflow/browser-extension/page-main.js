// Runs in the page (MAIN world) before Tutti boots. Tutti registers its WebMCP
// tools through document.modelContext.registerTool(tool, {signal}); this script
// provides that entry point (wrapping the native one when Chrome has WebMCP) so
// the extension sees the same tools without Chrome remote debugging.
(() => {
  const MARK = "__tuttiWebBridge";
  if (window[MARK]) return;
  window[MARK] = true;

  const tools = new Map();
  let port = null;

  function describe(tool) {
    return {
      name: tool.name,
      description: String(tool.description ?? ""),
      inputSchema: tool.inputSchema ?? {},
      annotations: { ...(tool.annotations ?? {}) }
    };
  }

  function publish() {
    port?.postMessage({ type: "tools", tools: [...tools.values()].map(describe) });
  }

  function serializeError(error) {
    return {
      code: "tool_failed",
      message: error instanceof Error ? error.message : String(error),
      name: error instanceof Error ? error.name : undefined
    };
  }

  const running = new Map();

  async function call({ id, tool: name, input }) {
    const tool = tools.get(name);
    if (!tool) {
      port?.postMessage({ type: "result", id, ok: false, error: { code: "tool_not_found", message: `No tool ${name} on this page` } });
      return;
    }
    if (tool.annotations?.readOnlyHint !== true) {
      port?.postMessage({ type: "result", id, ok: false, error: { code: "tool_not_read_only", message: `${name} is not read-only` } });
      return;
    }
    const controller = new AbortController();
    running.set(id, controller);
    try {
      const result = await tool.execute(input ?? {}, { signal: controller.signal });
      port?.postMessage({ type: "result", id, ok: true, result: JSON.parse(JSON.stringify(result ?? null)) });
    } catch (error) {
      port?.postMessage({ type: "result", id, ok: false, error: serializeError(error) });
    } finally {
      running.delete(id);
    }
  }

  function onPortMessage(event) {
    const message = event.data;
    if (message?.type === "call") call(message);
    else if (message?.type === "cancel") running.get(message.id)?.abort();
    else if (message?.type === "sync") publish();
  }

  // The isolated content script asks for a private channel; hand it one port.
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.[MARK] !== "ready" || port) return;
    const channel = new MessageChannel();
    port = channel.port1;
    port.onmessage = onPortMessage;
    window.postMessage({ [MARK]: "port" }, location.origin, [channel.port2]);
    publish();
  });
  window.postMessage({ [MARK]: "main-ready" }, location.origin);

  function track(tool, options) {
    const signal = options?.signal;
    if (signal?.aborted) return;
    tools.set(tool.name, tool);
    publish();
    signal?.addEventListener("abort", () => {
      if (tools.get(tool.name) === tool) {
        tools.delete(tool.name);
        publish();
      }
    }, { once: true });
  }

  const native = document.modelContext;
  let modelContext;
  if (native && typeof native.registerTool === "function") {
    const registerTool = (tool, options) => {
      track(tool, options);
      return native.registerTool(tool, options);
    };
    modelContext = new Proxy(native, {
      get(target, key) {
        if (key === "registerTool") return registerTool;
        const value = Reflect.get(target, key, target);
        return typeof value === "function" ? value.bind(target) : value;
      }
    });
  } else {
    modelContext = {
      registerTool(tool, options) {
        track(tool, options);
        return Promise.resolve();
      }
    };
  }
  Object.defineProperty(document, "modelContext", { configurable: true, get: () => modelContext });
})();
