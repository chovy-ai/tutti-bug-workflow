import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";
import {
  BRIDGE_VERSION,
  BridgeClient,
  EXTENSION_ID,
  HOST_NAME,
  chromeProfiles,
  createHub,
  doctor,
  install,
  lineReader,
  nativeFrame,
  nativeReader,
  newer,
  parseConnection,
  uninstall
} from "../tutti-web-bridge.mjs";

const BRIDGE = fileURLToPath(new URL("../tutti-web-bridge.mjs", import.meta.url));
const PAGE = "web-diagnostics:11111111-2222-3333-4444-555555555555";
const ACCOUNT = "acct-1";
const CONNECTION = `tutti-webmcp://page/${PAGE}?accountId=${ACCOUNT}`;

function tempEnv() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "twb-"));
  return {
    ...process.env,
    TUTTI_BUG_WORKFLOW_HOME: home,
    TUTTI_NATIVE_HOSTS_DIR: path.join(home, "hosts"),
    TUTTI_CHROME_USER_DATA: path.join(home, "chrome"),
    TUTTI_SKIP_REGISTRY: "1"
  };
}

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Spawns a real hub and plays the extension side over Native Messaging frames. */
function startHub(env, pages) {
  const child = spawn(process.execPath, [BRIDGE, "host", `chrome-extension://${EXTENSION_ID}/`], { env, stdio: ["pipe", "pipe", "inherit"] });
  const received = [];
  child.stdout.on("data", nativeReader((message) => {
    received.push(message);
    if (message.type !== "request") return;
    let payload;
    if (message.op === "list_pages") {
      payload = { ok: true, result: { extensionVersion: "0.1.0", pages } };
    } else if (message.op === "call") {
      const known = pages.some((page) => page.page === message.page);
      payload = known
        ? { ok: true, result: { tool: message.tool, input: message.input, pageSessionId: message.page, accountId: ACCOUNT } }
        : { ok: false, error: { code: "page_not_found", message: "no page" } };
    }
    child.stdin.write(nativeFrame({ type: "response", id: message.id, ...payload }));
  }));
  child.stdin.write(nativeFrame({ type: "hello", extensionVersion: "0.1.0", extensionId: EXTENSION_ID }));
  return { child, received };
}

async function waitForDiscovery(env, count = 1) {
  const run = path.join(env.TUTTI_BUG_WORKFLOW_HOME, "bridge", "run");
  for (let i = 0; i < 80; i++) {
    try {
      if (fs.readdirSync(run).filter((name) => name.endsWith(".json")).length >= count) return;
    } catch { /* not yet created */ }
    await wait(50);
  }
  throw new Error("hub never published its discovery file");
}

function stop(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null) return resolve(child.exitCode);
    child.on("exit", (code) => resolve(code));
    child.stdin.end();
  });
}

const PAGES = [{
  tabId: 7,
  url: "https://app.tutti.sh/platform/x",
  title: "Tutti",
  active: true,
  page: PAGE,
  accountId: ACCOUNT,
  connectionUrl: CONNECTION,
  tools: [{ name: "get_web_logs", readOnly: true }]
}];

describe("framing", () => {
  test("native frames survive arbitrary chunking", () => {
    const messages = [];
    const read = nativeReader((message) => messages.push(message));
    const bytes = Buffer.concat([nativeFrame({ a: 1 }), nativeFrame({ b: "中文" })]);
    for (const byte of bytes) read(Buffer.from([byte]));
    assert.deepEqual(messages, [{ a: 1 }, { b: "中文" }]);
  });

  test("line reader splits and skips garbage", () => {
    const messages = [];
    const read = lineReader((message) => messages.push(message));
    read(Buffer.from('{"a":1}\nnot json\n{"b"'));
    read(Buffer.from(":2}\n"));
    assert.deepEqual(messages, [{ a: 1 }, { b: 2 }]);
  });
});

test("parseConnection reads the Tutti connection link", () => {
  assert.deepEqual(parseConnection(CONNECTION), { page: PAGE, accountId: ACCOUNT });
  assert.equal(parseConnection("https://tutti.sh"), null);
  assert.equal(parseConnection("nonsense"), null);
});

test("newer compares semantic versions", () => {
  assert.equal(newer("0.1.10", "0.1.9"), true);
  assert.equal(newer("0.1.0", "0.1.0"), false);
  assert.equal(newer("0.0.9", "0.1.0"), false);
});

describe("hub core", () => {
  test("routes responses to the requesting client and fails pending on close", () => {
    const toExtension = [];
    const hub = createHub({ sendToExtension: (message) => toExtension.push(message) });
    const a = [];
    const b = [];
    const clientA = hub.attachClient((message) => a.push(message));
    const clientB = hub.attachClient((message) => b.push(message));

    clientA.onMessage({ type: "request", id: 1, op: "list_pages" });
    assert.equal(a.at(-1).error.code, "extension_not_connected");

    hub.onExtensionMessage({ type: "hello", extensionVersion: "0.1.0", extensionId: EXTENSION_ID });
    assert.equal(toExtension.at(-1).type, "hello");
    clientA.onMessage({ type: "request", id: 1, op: "list_pages" });
    clientB.onMessage({ type: "request", id: 1, op: "list_pages" });
    const [forA, forB] = toExtension.filter((message) => message.type === "request");
    assert.notEqual(forA.id, forB.id);

    hub.onExtensionMessage({ type: "response", id: forB.id, ok: true, result: "B" });
    assert.deepEqual(b.at(-1), { type: "response", id: 1, ok: true, result: "B", error: undefined });
    assert.equal(a.at(-1).error.code, "extension_not_connected");

    hub.close();
    assert.equal(a.at(-1).error.code, "hub_closed");
  });

  test("asks an older hub to step aside for a newer client", () => {
    let superseded = null;
    const hub = createHub({ sendToExtension: () => {}, onSuperseded: (version) => { superseded = version; } });
    const out = [];
    hub.attachClient((message) => out.push(message)).onMessage({ type: "hello", bridgeVersion: "99.0.0" });
    assert.equal(out[0].restarting, true);
    assert.equal(superseded, "99.0.0");
  });
});

describe("hub process with clients", () => {
  let env;
  let hub;
  before(async () => {
    env = tempEnv();
    hub = startHub(env, PAGES);
    await waitForDiscovery(env);
  });
  after(async () => {
    await stop(hub.child);
    fs.rmSync(env.TUTTI_BUG_WORKFLOW_HOME, { recursive: true, force: true });
  });

  test("several clients share one hub", async () => {
    const clients = [new BridgeClient(env), new BridgeClient(env), new BridgeClient(env)];
    const results = await Promise.all(clients.map((client) => client.callTool({ connection: CONNECTION, tool: "get_web_logs", input: { limit: 1 } })));
    for (const result of results) {
      assert.equal(result.ok, true);
      assert.deepEqual(result.result.input, { limit: 1 });
      assert.equal(result.result.pageSessionId, PAGE);
    }
    clients.forEach((client) => client.close());
  });

  test("unknown page and wrong account are page_not_found", async () => {
    const client = new BridgeClient(env);
    const missing = await client.callTool({ connection: "tutti-webmcp://page/web-diagnostics:nope?accountId=acct-1", tool: "get_web_logs" });
    assert.equal(missing.error.code, "page_not_found");
    const wrongAccount = await client.callTool({ connection: `tutti-webmcp://page/${PAGE}?accountId=other`, tool: "get_web_logs" });
    assert.equal(wrongAccount.error.code, "page_not_found");
    client.close();
  });

  test("MCP server lists and calls tools over stdio", async () => {
    const child = spawn(process.execPath, [BRIDGE, "mcp"], { env, stdio: ["pipe", "pipe", "inherit"] });
    const responses = new Map();
    child.stdout.on("data", lineReader((message) => responses.set(message.id, message)));
    const send = (message) => child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", ...message })}\n`);
    send({ id: 1, method: "initialize", params: { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "0" } } });
    send({ method: "notifications/initialized" });
    send({ id: 2, method: "tools/list" });
    send({ id: 3, method: "tools/call", params: { name: "list_tutti_pages", arguments: {} } });
    send({ id: 4, method: "tools/call", params: { name: "call_tutti_tool", arguments: { connection: CONNECTION, tool: "get_web_logs", input: { range: "10m" } } } });
    for (let i = 0; i < 100 && responses.size < 4; i++) await wait(50);
    child.stdin.end();

    assert.equal(responses.get(1).result.serverInfo.name, "tutti-web");
    assert.deepEqual(responses.get(2).result.tools.map((tool) => tool.name), ["list_tutti_pages", "call_tutti_tool"]);
    const pages = JSON.parse(responses.get(3).result.content[0].text).pages;
    assert.equal(pages[0].page, PAGE);
    const call = responses.get(4).result;
    assert.equal(call.isError, false);
    assert.deepEqual(JSON.parse(call.content[0].text).input, { range: "10m" });
  });
});

test("hub removes its discovery file and socket when Chrome disconnects", async () => {
  const env = tempEnv();
  const { child } = startHub(env, PAGES);
  await waitForDiscovery(env);
  const run = path.join(env.TUTTI_BUG_WORKFLOW_HOME, "bridge", "run");
  assert.equal(await stop(child), 0);
  assert.deepEqual(fs.readdirSync(run), []);
  fs.rmSync(env.TUTTI_BUG_WORKFLOW_HOME, { recursive: true, force: true });
});

test("clients aggregate pages from two Chrome profiles", async () => {
  const env = tempEnv();
  const other = { ...PAGES[0], page: "web-diagnostics:other", connectionUrl: null };
  const first = startHub(env, PAGES);
  const second = startHub(env, [other]);
  await waitForDiscovery(env, 2);
  const client = new BridgeClient(env);
  const listed = await client.listPages();
  assert.deepEqual(listed.result.pages.map((page) => page.page).sort(), [PAGE, "web-diagnostics:other"].sort());
  const call = await client.callTool({ connection: CONNECTION, tool: "get_web_logs" });
  assert.equal(call.ok, true);
  client.close();
  await Promise.all([stop(first.child), stop(second.child)]);
  fs.rmSync(env.TUTTI_BUG_WORKFLOW_HOME, { recursive: true, force: true });
});

test("without a hub the client explains what is missing", async () => {
  const env = tempEnv();
  const client = new BridgeClient(env);
  const before = await client.listPages();
  assert.equal(before.error.code, "host_not_installed");
  install({ env });
  const afterInstall = await client.listPages();
  assert.equal(afterInstall.error.code, "extension_not_connected");
  fs.rmSync(env.TUTTI_BUG_WORKFLOW_HOME, { recursive: true, force: true });
});

describe("install", () => {
  test("registers the host for the fixed extension and copies files", () => {
    const env = tempEnv();
    const result = install({ env });
    const manifest = JSON.parse(fs.readFileSync(path.join(env.TUTTI_NATIVE_HOSTS_DIR, `${HOST_NAME}.json`), "utf8"));
    assert.equal(manifest.name, HOST_NAME);
    assert.equal(manifest.type, "stdio");
    assert.deepEqual(manifest.allowed_origins, [`chrome-extension://${EXTENSION_ID}/`]);
    assert.equal(manifest.path, result.launcher);
    const launcher = fs.readFileSync(result.launcher, "utf8");
    assert.ok(launcher.includes(process.execPath), "launcher pins the absolute node path");
    assert.ok(launcher.includes(path.join(BRIDGE_VERSION, "tutti-web-bridge.mjs")));
    assert.ok(fs.existsSync(path.join(result.extensionDir, "manifest.json")));
    assert.equal(result.extensionVersion, JSON.parse(fs.readFileSync(path.join(result.extensionDir, "manifest.json"), "utf8")).version);

    fs.mkdirSync(path.join(env.TUTTI_BUG_WORKFLOW_HOME, "bridge", "0.0.1"));
    install({ env });
    assert.equal(fs.existsSync(path.join(env.TUTTI_BUG_WORKFLOW_HOME, "bridge", "0.0.1")), false, "old versions are pruned");

    uninstall({ env });
    assert.equal(fs.existsSync(manifest.path), false);
    assert.equal(fs.existsSync(path.join(env.TUTTI_NATIVE_HOSTS_DIR, `${HOST_NAME}.json`)), false);
    fs.rmSync(env.TUTTI_BUG_WORKFLOW_HOME, { recursive: true, force: true });
  });

  test("installed launcher starts a working hub", { skip: process.platform === "win32" }, async () => {
    const env = tempEnv();
    const { launcher } = install({ env });
    const child = spawn(launcher, [`chrome-extension://${EXTENSION_ID}/`], { env, stdio: ["pipe", "pipe", "inherit"] });
    const hello = new Promise((resolve) => child.stdout.on("data", nativeReader(resolve)));
    child.stdin.write(nativeFrame({ type: "hello", extensionVersion: "0.0.1", extensionId: EXTENSION_ID }));
    const reply = await hello;
    assert.equal(reply.hubVersion, BRIDGE_VERSION);
    assert.equal(reply.extensionVersion, JSON.parse(fs.readFileSync(path.join(env.TUTTI_BUG_WORKFLOW_HOME, "browser-extension", "manifest.json"), "utf8")).version);
    await stop(child);
    fs.rmSync(env.TUTTI_BUG_WORKFLOW_HOME, { recursive: true, force: true });
  });
});

test("doctor finds the extension in Chrome profiles and reports next steps", async () => {
  const env = tempEnv();
  const profile = path.join(env.TUTTI_CHROME_USER_DATA, "Profile 1");
  fs.mkdirSync(profile, { recursive: true });
  fs.writeFileSync(path.join(profile, "Preferences"), JSON.stringify({ extensions: { ui: { developer_mode: true } } }));
  fs.writeFileSync(path.join(profile, "Secure Preferences"), JSON.stringify({ extensions: { settings: { [EXTENSION_ID]: { path: "/x", disable_reasons: [] } } } }));
  fs.mkdirSync(path.join(env.TUTTI_CHROME_USER_DATA, "Default"));
  fs.writeFileSync(path.join(env.TUTTI_CHROME_USER_DATA, "Default", "Secure Preferences"), JSON.stringify({ extensions: { settings: { [EXTENSION_ID]: { path: "/x", disable_reasons: [1] } } } }));

  assert.deepEqual(chromeProfiles(env).map(({ profile: name, installed, enabled }) => ({ name, installed, enabled })).sort((a, b) => a.name.localeCompare(b.name)), [
    { name: "Default", installed: true, enabled: false },
    { name: "Profile 1", installed: true, enabled: true }
  ]);

  const notInstalled = await doctor({ env });
  assert.equal(notInstalled.ready, false);
  assert.ok(notInstalled.next.some((step) => step.includes("install")));

  install({ env });
  const { child } = startHub(env, PAGES);
  await waitForDiscovery(env);
  const ready = await doctor({ env });
  assert.equal(ready.ready, true, JSON.stringify(ready.next));
  assert.equal(ready.hubs[0].extension.connected, true);
  await stop(child);
  fs.rmSync(env.TUTTI_BUG_WORKFLOW_HOME, { recursive: true, force: true });
});
