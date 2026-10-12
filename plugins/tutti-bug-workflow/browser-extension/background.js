// Holds one Native Messaging connection to the local tutti-web-bridge hub and
// routes hub requests to the Tutti tabs that registered tools.
const HOST = "io.tutti.web_bridge";
const DEFAULT_TIMEOUT_MS = 30000;
const IDENTITY = /Page identity: ([^;]+); Account identity: ([^;]+);/;

const pages = new Map(); // tabId -> { port, tools }
const calls = new Map(); // callId -> { hubId, tabId, timer }
let native = null;
let nativeState = { connected: false, error: null, hubVersion: null, since: null };
let retryDelay = 1000;
let retryTimer = null;
let nextCallId = 1;

function identityOf(tools) {
  for (const tool of tools) {
    const match = IDENTITY.exec(tool.description);
    if (match) return { page: match[1].trim(), accountId: match[2].trim() };
  }
  return null;
}

function connectionUrl(identity) {
  const url = new URL("tutti-webmcp://page/");
  url.pathname = identity.page;
  url.searchParams.set("accountId", identity.accountId);
  return url.href;
}

async function describePages() {
  const result = [];
  for (const [tabId, entry] of pages) {
    let tab = null;
    try {
      tab = await chrome.tabs.get(tabId);
    } catch {
      continue;
    }
    const identity = identityOf(entry.tools);
    result.push({
      tabId,
      url: tab.url ?? null,
      title: tab.title ?? null,
      active: tab.active,
      windowId: tab.windowId,
      page: identity?.page ?? null,
      accountId: identity?.accountId ?? null,
      connectionUrl: identity ? connectionUrl(identity) : null,
      tools: entry.tools.map(({ name, description, inputSchema, annotations }) => ({
        name, description, inputSchema, readOnly: annotations?.readOnlyHint === true
      }))
    });
  }
  return result;
}

function reply(hubId, payload) {
  try {
    native?.postMessage({ type: "response", id: hubId, ...payload });
  } catch {
    // Native port gone; the hub fails its own pending requests on disconnect.
  }
}

function startCall(hubId, request) {
  const matches = [...pages].filter(([, entry]) => {
    const identity = identityOf(entry.tools);
    return identity && identity.page === request.page
      && (!request.accountId || identity.accountId === request.accountId);
  });
  if (matches.length === 0) {
    reply(hubId, { ok: false, error: { code: "page_not_found", message: `No open Tutti page with identity ${request.page}` } });
    return;
  }
  if (matches.length > 1) {
    reply(hubId, { ok: false, error: { code: "page_ambiguous", message: `${matches.length} tabs report identity ${request.page}` } });
    return;
  }
  const [tabId, entry] = matches[0];
  const callId = nextCallId++;
  const timer = setTimeout(() => {
    calls.delete(callId);
    entry.port.postMessage({ type: "cancel", id: callId });
    reply(hubId, { ok: false, error: { code: "timeout", message: "Tutti page did not answer in time" } });
  }, request.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  calls.set(callId, { hubId, tabId, timer });
  entry.port.postMessage({ type: "call", id: callId, tool: request.tool, input: request.input ?? {} });
}

async function onNativeMessage(message) {
  if (message?.type === "hello") {
    nativeState = { ...nativeState, connected: true, hubVersion: message.hubVersion ?? null };
    maybeReload(message.extensionVersion);
    return;
  }
  if (message?.type !== "request") return;
  if (message.op === "list_pages") {
    reply(message.id, { ok: true, result: { extensionVersion: chrome.runtime.getManifest().version, pages: await describePages() } });
  } else if (message.op === "call") {
    startCall(message.id, message);
  } else {
    reply(message.id, { ok: false, error: { code: "unknown_op", message: `Unknown op ${message.op}` } });
  }
}

function newer(a, b) {
  const pa = String(a).split(".").map(Number);
  const pb = String(b).split(".").map(Number);
  for (let i = 0; i < 3; i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  return false;
}

// Setup copies newer extension files over the unpacked directory; reload to pick
// them up. Rate-limited so a mismatched install cannot cause a reload loop.
async function maybeReload(installedVersion) {
  if (!installedVersion || !newer(installedVersion, chrome.runtime.getManifest().version)) return;
  const { lastReloadAt = 0 } = await chrome.storage.local.get("lastReloadAt");
  if (Date.now() - lastReloadAt < 10 * 60 * 1000) return;
  await chrome.storage.local.set({ lastReloadAt: Date.now() });
  chrome.runtime.reload();
}

function scheduleReconnect() {
  if (retryTimer) return;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    ensureNative();
  }, retryDelay);
  retryDelay = Math.min(retryDelay * 2, 30000);
}

function ensureNative() {
  if (native) return;
  try {
    native = chrome.runtime.connectNative(HOST);
  } catch (error) {
    nativeState = { connected: false, error: String(error?.message ?? error), hubVersion: null, since: null };
    scheduleReconnect();
    return;
  }
  nativeState = { connected: false, error: null, hubVersion: null, since: Date.now() };
  native.onMessage.addListener(onNativeMessage);
  native.onDisconnect.addListener(() => {
    nativeState = { connected: false, error: chrome.runtime.lastError?.message ?? "disconnected", hubVersion: null, since: null };
    native = null;
    scheduleReconnect();
  });
  native.postMessage({ type: "hello", extensionVersion: chrome.runtime.getManifest().version, extensionId: chrome.runtime.id });
  retryDelay = 1000;
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== "tutti-page" || !port.sender?.tab?.id) return;
  const tabId = port.sender.tab.id;
  pages.set(tabId, { port, tools: [] });
  port.onMessage.addListener((message) => {
    const entry = pages.get(tabId);
    if (!entry || entry.port !== port) return;
    if (message?.type === "tools") {
      entry.tools = Array.isArray(message.tools) ? message.tools : [];
    } else if (message?.type === "result") {
      const call = calls.get(message.id);
      if (!call || call.tabId !== tabId) return;
      clearTimeout(call.timer);
      calls.delete(message.id);
      reply(call.hubId, message.ok ? { ok: true, result: message.result } : { ok: false, error: message.error });
    }
  });
  port.onDisconnect.addListener(() => {
    if (pages.get(tabId)?.port !== port) return;
    pages.delete(tabId);
    for (const [callId, call] of calls) {
      if (call.tabId !== tabId) continue;
      clearTimeout(call.timer);
      calls.delete(callId);
      reply(call.hubId, { ok: false, error: { code: "page_closed", message: "Tutti page closed or reloaded during the call" } });
    }
  });
  ensureNative();
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type !== "status") return false;
  describePages().then((list) => sendResponse({ native: nativeState, pages: list }));
  return true;
});

chrome.alarms.create("tutti-web-bridge-reconnect", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener(() => ensureNative());
chrome.runtime.onStartup.addListener(() => ensureNative());
chrome.runtime.onInstalled.addListener(() => ensureNative());
ensureNative();
