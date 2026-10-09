import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { PassThrough } from 'node:stream';
import { createInterface } from 'node:readline';
import { DiagnosticsClient, parseConnection, collectLogs, serve } from '../scripts/diagnostics-mcp.mjs';

const page = 'web-diagnostics:00000000-0000-4000-8000-000000000001';
const id = '00000000-0000-4000-8000-000000000002';
const token = 'x'.repeat(43);
const question = '2026-10-08T12:00:00Z';
const until = Date.parse(question);
function record(sequence) { return { id: sequence, userId: 'alice', pageSessionId: page, occurredAtUnixMs: until - sequence, event: 'failure', details: { token: 'keep-original', url: 'https://tutti.sh/private?secret=original' } }; }
async function endpoint(t, read) {
  const calls = [];
  const server = createServer(async (req, res) => {
    try {
      assert.equal(req.url, `/api/desktop/v2/web-diagnostics/connections/${id}/mcp`);
      assert.equal(req.headers.authorization, `Bearer ${token}`);
      assert.equal(req.headers.accept, 'application/json, text/event-stream');
      let text = ''; for await (const chunk of req) text += chunk;
      const message = JSON.parse(text); calls.push(message);
      if (message.method === 'notifications/initialized') { res.writeHead(202); res.end(); return; }
      let result;
      if (message.method === 'initialize') result = { protocolVersion: '2025-06-18', serverInfo: { name: 'tutti-page-diagnostics' }, capabilities: { tools: {} } };
      else if (message.method === 'tools/list') result = { tools: [{ name: 'get_web_logs', description: `Page ${page}`, annotations: { readOnlyHint: true } }] };
      else if (message.method === 'tools/call') {
        const snapshot = await read(message.params.arguments);
        result = { content: [{ type: 'text', text: JSON.stringify(snapshot) }], structuredContent: snapshot };
      } else throw new Error('Unexpected MCP method');
      res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ jsonrpc: '2.0', id: message.id, result }));
    } catch (error) { res.writeHead(500); res.end(error.message); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  return { link: `http://127.0.0.1:${server.address().port}/api/desktop/v2/web-diagnostics/connections/${id}/mcp#${token}`, calls };
}
function snapshot(records, more = false) { return { pageSessionId: page, sinceUnixMs: until - 600000, untilUnixMs: until, records, truncated: more, nextBeforeSequence: more ? records.at(-1).id : null, redacted: false, retention: 'current-page-memory' }; }

test('connection capability stays in Authorization and rejected links cannot redirect it', () => {
  const link = `https://tutti.sh/api/desktop/v2/web-diagnostics/connections/${id}/mcp#${token}`;
  assert.equal(parseConnection(link).token, token);
  assert.ok(!parseConnection(link).endpoint.includes(token));
  for (const invalid of [link.replace('tutti.sh', 'evil.test'), link.replace('https:', 'http:'), link.split('#')[0], link.replace('/mcp#', '/mcp?secret=x#')]) assert.throws(() => parseConnection(invalid));
});

test('direct HTTP MCP collects all pages in the original fixed window without redaction', async t => {
  const remote = await endpoint(t, query => {
    assert.equal(query.untilUnixMs, until); assert.equal(query.range, '10m'); assert.equal(query.level, undefined);
    return query.beforeSequence === undefined ? snapshot([record(3), record(2)], true) : snapshot([record(1)]);
  });
  const client = new DiagnosticsClient(remote.link); await client.initialize();
  const collected = await collectLogs(client, question);
  const lines = collected.text.trim().split('\n').map(line => JSON.parse(line));
  assert.equal(collected.metadata.recordCount, 3); assert.equal(collected.metadata.pages, 2);
  assert.deepEqual(lines.slice(1).map(value => value.id), [3, 2, 1]);
  assert.ok(collected.text.includes('keep-original')); assert.ok(collected.text.includes('?secret=original'));
  assert.ok(!collected.text.includes(token)); assert.equal(collected.metadata.redacted, false);
  assert.equal(remote.calls.filter(value => value.method === 'tools/call')[1].params.arguments.beforeSequence, 2);
});

test('collector rejects wrong page, changed window, mixed Account, and non-advancing cursor', async t => {
  for (const invalid of [
    { ...snapshot([record(1)]), pageSessionId: 'wrong' },
    { ...snapshot([record(1)]), untilUnixMs: until + 1 },
    snapshot([record(2), { ...record(1), userId: 'bob' }]),
    { ...snapshot([record(2)], true), nextBeforeSequence: 3 }
  ]) {
    const remote = await endpoint(t, () => invalid);
    const client = new DiagnosticsClient(remote.link); await client.initialize();
    await assert.rejects(collectLogs(client, question));
  }
});

test('shipped stdio MCP writes one evidence attachment and returns its coverage and digest', async t => {
  const remote = await endpoint(t, () => snapshot([record(1)]));
  const directory = await mkdtemp(join(tmpdir(), 'tutti-diagnostics-test-')); t.after(() => rm(directory, { recursive: true, force: true }));
  const input = new PassThrough(); const output = new PassThrough();
  const lines = createInterface({ input: output }); const responses = new Map(); const pending = new Map();
  lines.on('line', text => { const result = JSON.parse(text); responses.set(result.id, result); pending.get(result.id)?.(result); });
  const running = serve(input, output); t.after(async () => { input.end(); await running; lines.close(); output.end(); });
  function rpc(id, method, params) { const received = new Promise(resolve => pending.set(id, resolve)); input.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); return received; }
  assert.equal((await rpc(1, 'initialize', { protocolVersion: '2025-06-18' })).result.serverInfo.name, 'tutti-diagnostics');
  assert.ok((await rpc(2, 'tools/list')).result.tools.some(tool => tool.name === 'collect_web_logs'));
  const path = join(directory, 'web-logs.log');
  const result = await rpc(3, 'tools/call', { name: 'collect_web_logs', arguments: { connection_url: remote.link, question_time: question, output_path: path } });
  assert.equal(result.result.isError, undefined);
  assert.equal(result.result.structuredContent.outputPath, path);
  assert.match(result.result.structuredContent.sha256, /^[a-f0-9]{64}$/u);
  const text = await readFile(path, 'utf8'); assert.ok(text.includes('keep-original'));
  assert.equal(JSON.parse(text.split('\n')[0]).recordCount, 1);
});


test('client accepts bounded raw logs even when JSON escaping expands MCP text content', async t => {
  const records = Array.from({ length: 31 }, (_, index) => ({ ...record(index + 1), details: { message: '\\"'.repeat(2000) } }));
  const remote = await endpoint(t, () => snapshot(records));
  const client = new DiagnosticsClient(remote.link); await client.initialize();
  const result = await client.read({ limit: 200 });
  assert.equal(result.records.length, records.length);
  assert.equal(result.records[0].details.message, records[0].details.message);
});


test('completed pagination still reports truncated record contents', async t => {
  const remote = await endpoint(t, () => snapshot([{ ...record(1), truncated: true }]));
  const client = new DiagnosticsClient(remote.link); await client.initialize();
  const collected = await collectLogs(client, question);
  assert.equal(collected.metadata.paginationComplete, true);
  assert.equal(collected.metadata.recordTruncationCount, 1);
  assert.equal(collected.metadata.truncated, true);
});
