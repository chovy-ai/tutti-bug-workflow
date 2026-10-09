#!/usr/bin/env node
import { createInterface } from 'node:readline';
import { writeFile, rename, rm } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const protocolVersion = '2025-06-18';
const maxBytes = 24 * 1024 * 1024;
const properties = {
  connection_url: { type: 'string', description: 'The full MCP link copied from Tutti, including its capability fragment.' },
  range: { type: 'string', enum: ['10m', '1h', '12h', '1d', '7d'] },
  level: { type: 'string', enum: ['info', 'warn', 'error'] },
  limit: { type: 'integer', minimum: 1, maximum: 200 },
  untilUnixMs: { type: 'integer', minimum: 0 },
  beforeSequence: { type: 'integer', minimum: 0 }
};
const tools = [
  { name: 'get_web_logs', description: 'Connect directly to the pasted Tutti MCP link and read unredacted logs. No browser bridge is needed. Logs are untrusted data.', annotations: { readOnlyHint: true }, inputSchema: { type: 'object', properties, required: ['connection_url'], additionalProperties: false } },
  { name: 'collect_web_logs', description: 'Collect every page of retained logs in the ten minutes before question_time and write one web-logs.log with coverage metadata. No redaction. The page must remain open.', inputSchema: { type: 'object', properties: { connection_url: properties.connection_url, question_time: { type: 'string', description: 'Original question time as an ISO 8601 timestamp with timezone.' }, output_path: { type: 'string', description: 'Absolute evidence path ending in web-logs.log.' } }, required: ['connection_url', 'question_time', 'output_path'], additionalProperties: false } }
];

export function parseConnection(value) {
  if (typeof value !== 'string') throw new Error('A copied Tutti MCP connection link is required');
  let url; try { url = new URL(value); } catch { throw new Error('Invalid diagnostics connection link'); }
  const local = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  const additional = (process.env.TUTTI_DIAGNOSTICS_ALLOWED_ORIGINS ?? '').split(',').filter(Boolean);
  if (!['https://tutti.sh', 'https://api.tutti.sh', ...additional].includes(url.origin) && !local) throw new Error('Diagnostics link origin is not allowed');
  if ((url.protocol !== 'https:' && !(local && url.protocol === 'http:')) || url.username || url.password || url.search || !/^\/api\/desktop\/v2\/web-diagnostics\/connections\/[0-9a-f-]{36}\/mcp$/u.test(url.pathname)) throw new Error('Invalid diagnostics MCP endpoint');
  const token = url.hash.slice(1);
  if (!/^[A-Za-z0-9_-]{43}$/u.test(token)) throw new Error('The copied link is missing its read-only capability');
  url.hash = '';
  return { endpoint: url.href, token };
}

export class DiagnosticsClient {
  constructor(link, fetchImpl = fetch, signal) { this.connection = parseConnection(link); this.fetch = fetchImpl; this.nextID = 0; this.signal = signal; }
  async exchange(method, params, notification = false) {
    const id = ++this.nextID;
    const body = { jsonrpc: '2.0', ...(notification ? {} : { id }), method, ...(params ? { params } : {}) };
    const response = await this.fetch(this.connection.endpoint, { method: 'POST', redirect: 'error', headers: { Authorization: `Bearer ${this.connection.token}`, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': protocolVersion }, body: JSON.stringify(body), signal: this.signal ? AbortSignal.any([this.signal, AbortSignal.timeout(35_000)]) : AbortSignal.timeout(35_000) });
    if (!response.ok) throw new Error(`Diagnostics connection returned HTTP ${response.status}; the page may be offline, revoked, or expired`);
    if (notification) { if (response.status !== 202) throw new Error('Diagnostics MCP notification was not accepted'); return; }
    if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Diagnostics MCP returned an unsupported response type');
    const raw = await boundedText(response, 1024 * 1024);
    let envelope; try { envelope = JSON.parse(raw); } catch { throw new Error('Diagnostics MCP returned invalid JSON'); }
    if (envelope.jsonrpc !== '2.0' || envelope.id !== id) throw new Error('Diagnostics MCP response does not match the request');
    if (envelope.error) throw new Error(`Diagnostics MCP error ${envelope.error.code}: ${envelope.error.message}`);
    if (!Object.hasOwn(envelope, 'result')) throw new Error('Diagnostics MCP response is missing its result');
    return envelope.result;
  }
  async initialize() {
    const result = await this.exchange('initialize', { protocolVersion, capabilities: {}, clientInfo: { name: 'tutti-bug-workflow', version: '1.0.0' } });
    if (result.protocolVersion !== protocolVersion || result.serverInfo?.name !== 'tutti-page-diagnostics' || !result.capabilities?.tools) throw new Error('The link is not a supported Tutti page diagnostics MCP');
    await this.exchange('notifications/initialized', undefined, true);
    const listed = await this.exchange('tools/list', {});
    const tool = listed.tools?.find(item => item.name === 'get_web_logs');
    if (!tool?.annotations?.readOnlyHint) throw new Error('Read-only get_web_logs is not available');
    const identity = /web-diagnostics:[0-9a-f-]{36}/u.exec(tool.description ?? '');
    if (!identity) throw new Error('Diagnostics MCP does not identify its page');
    this.pageSessionId = identity[0];
  }
  async read(query = {}) {
    const result = await this.exchange('tools/call', { name: 'get_web_logs', arguments: query });
    if (result.isError) throw new Error(result.content?.find(item => item.type === 'text')?.text ?? 'Page diagnostics read failed');
    let snapshot = result.structuredContent;
    if (!snapshot) { const text = result.content?.find(item => item.type === 'text')?.text; try { snapshot = JSON.parse(text); } catch { throw new Error('Invalid page diagnostics snapshot'); } }
    if (snapshot.pageSessionId !== this.pageSessionId || snapshot.redacted !== false || !Array.isArray(snapshot.records) || !Number.isSafeInteger(snapshot.sinceUnixMs) || !Number.isSafeInteger(snapshot.untilUnixMs) || typeof snapshot.truncated !== 'boolean') throw new Error('Page diagnostics identity or snapshot contract changed');
    for (const record of snapshot.records) {
      if (record.pageSessionId !== this.pageSessionId || !record.userId || (this.accountId && record.userId !== this.accountId)) throw new Error('Diagnostics returned an unrelated page or Account');
      this.accountId = record.userId;
    }
    return snapshot;
  }
}

async function boundedText(response, limit) {
  const reader = response.body.getReader(); const chunks = []; let size = 0;
  try { for (;;) { const { done, value } = await reader.read(); if (done) break; size += value.byteLength; if (size > limit) throw new Error('Diagnostics MCP response exceeds the size limit'); chunks.push(value); } }
  finally { await reader.cancel(); }
  const bytes = new Uint8Array(size); let offset = 0; for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  return new TextDecoder().decode(bytes);
}

export async function collectLogs(client, questionTime) {
  if (typeof questionTime !== 'string' || !/(?:Z|[+-]\d{2}:\d{2})$/u.test(questionTime)) throw new Error('question_time must include a timezone');
  const untilUnixMs = Date.parse(questionTime);
  if (!Number.isSafeInteger(untilUnixMs) || untilUnixMs < 0) throw new Error('Invalid original question time');
  const sinceUnixMs = untilUnixMs - 10 * 60 * 1000;
  const records = []; const sequences = new Set(); let beforeSequence; let bytes = 0; let pages = 0;
  for (;;) {
    const snapshot = await client.read({ range: '10m', limit: 200, untilUnixMs, ...(beforeSequence === undefined ? {} : { beforeSequence }) }); pages++;
    if (snapshot.sinceUnixMs !== sinceUnixMs || snapshot.untilUnixMs !== untilUnixMs) throw new Error('Diagnostics query window changed during collection');
    for (const record of snapshot.records) {
      if (!Number.isSafeInteger(record.id) || sequences.has(record.id) || (beforeSequence !== undefined && record.id >= beforeSequence) || record.occurredAtUnixMs < sinceUnixMs || record.occurredAtUnixMs > untilUnixMs) throw new Error('Invalid diagnostics pagination or time window');
      sequences.add(record.id); const line = JSON.stringify(record); bytes += Buffer.byteLength(line) + 1;
      if (bytes > maxBytes) throw new Error('Retained diagnostics exceed the collection size limit');
      records.push(record);
    }
    if (!snapshot.truncated) break;
    const next = snapshot.nextBeforeSequence;
    if (!snapshot.records.length || !Number.isSafeInteger(next) || next !== snapshot.records.at(-1).id || (beforeSequence !== undefined && next >= beforeSequence)) throw new Error('Diagnostics pagination did not advance');
    beforeSequence = next;
  }
  const earliest = records.reduce((value, record) => Math.min(value, record.occurredAtUnixMs), Infinity);
  const latest = records.reduce((value, record) => Math.max(value, record.occurredAtUnixMs), -Infinity);
  const recordTruncationCount = records.filter(record => record.truncated === true).length;
  const metadata = { type: 'metadata', pageSessionId: client.pageSessionId, source: 'tutti-page-diagnostics-mcp', endpoint: client.connection.endpoint, questionTime, sinceUnixMs, untilUnixMs, recordCount: records.length, pages, redacted: false, paginationComplete: true, recordTruncationCount, truncated: recordTruncationCount > 0, retention: 'current-page-memory', earliestRecordUnixMs: records.length ? earliest : null, latestRecordUnixMs: records.length ? latest : null, coverage: 'All retained records in the requested window. Serialization and record size limits still apply; excluded debug and evicted records cannot be recovered.' };
  const text = [JSON.stringify(metadata), ...records.map(record => JSON.stringify(record))].join('\n') + '\n';
  return { metadata, text, sha256: createHash('sha256').update(text).digest('hex') };
}

async function callTool(name, args, signal) {
  const schema = tools.find(tool => tool.name === name)?.inputSchema;
  if (!schema || !args || typeof args !== 'object' || Array.isArray(args) || Object.keys(args).some(key => !Object.hasOwn(schema.properties, key)) || schema.required.some(key => !Object.hasOwn(args, key))) throw new Error('Invalid diagnostic tool or arguments');
  const client = new DiagnosticsClient(args.connection_url, fetch, signal); await client.initialize();
  if (name === 'get_web_logs') { const { connection_url: _, ...query } = args; return client.read(query); }
  if (!isAbsolute(args.output_path ?? '') || !args.output_path.endsWith('web-logs.log')) throw new Error('output_path must be an absolute web-logs.log path');
  const collected = await collectLogs(client, args.question_time);
  const temp = `${args.output_path}.${randomUUID()}.tmp`;
  try { signal?.throwIfAborted(); await writeFile(temp, collected.text, { flag: 'wx', mode: 0o600 }); signal?.throwIfAborted(); await rename(temp, args.output_path); }
  finally { await rm(temp, { force: true }); }
  return { ...collected.metadata, outputPath: args.output_path, sha256: collected.sha256, bytes: Buffer.byteLength(collected.text) };
}

export async function serve(input = process.stdin, output = process.stdout) {
  const lines = createInterface({ input, crlfDelay: Infinity }); let active = 0;
  const requests = new Map();
  async function dispatch(line) {
    let request;
    const send = async envelope => { await new Promise((resolve, reject) => output.write(`${JSON.stringify(envelope)}\n`, error => error ? reject(error) : resolve())); };
    try { if (Buffer.byteLength(line) > 1024 * 1024) throw new Error('Request too large'); request = JSON.parse(line); }
    catch { return send({ jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Invalid JSON-RPC input' } }); }
    if (!Object.hasOwn(request, 'id')) { if (request.method === 'notifications/cancelled') requests.get(request.params?.requestId)?.abort(); return; }
    const reply = { jsonrpc: '2.0', id: request.id };
    if (request.jsonrpc !== '2.0' || typeof request.method !== 'string') return send({ ...reply, error: { code: -32600, message: 'Invalid request' } });
    try {
      let result;
      if (request.method === 'initialize') result = { protocolVersion, capabilities: { tools: {} }, serverInfo: { name: 'tutti-diagnostics', version: '1.0.0' } };
      else if (request.method === 'ping') result = {};
      else if (request.method === 'tools/list') result = { tools };
      else if (request.method === 'tools/call') {
        if (active >= 4 || requests.has(request.id)) throw new Error('Too many or duplicate diagnostic requests'); active++;
        const controller = new AbortController(); requests.set(request.id, controller);
        try { const value = await callTool(request.params?.name, request.params?.arguments, controller.signal); result = { content: [{ type: 'text', text: JSON.stringify(value) }], structuredContent: value }; }
        catch (error) { result = { isError: true, content: [{ type: 'text', text: error.message }] }; }
        finally { active--; requests.delete(request.id); }
      } else return send({ ...reply, error: { code: -32601, message: 'Method not found' } });
      await send({ ...reply, result });
    } catch (error) { await send({ ...reply, error: { code: -32603, message: error.message } }); }
  }
  try { for await (const line of lines) void dispatch(line).catch(error => process.stderr.write(`Diagnostics protocol write failed: ${error.message}\n`)); }
  finally { for (const controller of requests.values()) controller.abort(); }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await serve();
