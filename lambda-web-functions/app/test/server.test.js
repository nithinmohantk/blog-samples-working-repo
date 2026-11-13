// Run with: node --test test/      (Node.js 24 or later; no packages)
// Besides checking behaviour, the last tests measure what a Web Function is billed for: CPU time,
// which is not the same thing as how long requests take.
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { performance } = require('node:perf_hooks');
const { createServer, listenAddress } = require('../index.js');

let server;
let base;
const metrics = {};

test.before(async () => {
  server = createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${server.address().port}`;
});

test.after(async () => {
  await new Promise((resolve) => server.close(resolve));
  if (process.env.METRICS_FILE) fs.writeFileSync(process.env.METRICS_FILE, JSON.stringify(metrics, null, 2));
});

const cpuSeconds = (usage) => (usage.user + usage.system) / 1e6;

test('the listen address comes from AWS_LAMBDA_HTTP_ENDPOINT', () => {
  process.env.AWS_LAMBDA_HTTP_ENDPOINT = '0.0.0.0:8080';
  assert.deepEqual(listenAddress(), { host: '0.0.0.0', port: 8080 });
  delete process.env.AWS_LAMBDA_HTTP_ENDPOINT;
  assert.deepEqual(listenAddress(), { host: '127.0.0.1', port: 3000 });
});

test('health check answers before start-up work has finished', async () => {
  const response = await fetch(`${base}/healthz`);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: 'ok' });
});

test('appointments can be listed and filtered', async () => {
  const all = await (await fetch(`${base}/api/appointments`)).json();
  assert.equal(all.items.length, 3);
  const north = await (await fetch(`${base}/api/appointments?clinic=north`)).json();
  assert.deepEqual(north.items.map((a) => a.id), ['apt-1001', 'apt-1002']);
});

test('the platform request id is used, and only the last forwarded address is trusted', async () => {
  const response = await fetch(`${base}/api/appointments`, {
    headers: { 'lambda-web-request-id': 'req-123', 'x-forwarded-for': '10.9.9.9, 203.0.113.7' },
  });
  const body = await response.json();
  assert.equal(body.requestId, 'req-123');
  assert.equal(body.client, '203.0.113.7');
});

test('an unknown path is a 404 with a JSON body', async () => {
  const response = await fetch(`${base}/api/nothing`);
  assert.equal(response.status, 404);
  assert.equal((await response.json()).error, 'not found');
});

test('events are streamed one at a time', async () => {
  const response = await fetch(`${base}/events?count=5`);
  assert.equal(response.headers.get('content-type'), 'text/event-stream');
  let chunks = 0;
  let text = '';
  for await (const chunk of response.body) {
    chunks += 1;
    text += Buffer.from(chunk).toString();
  }
  assert.equal(text.match(/^data: /gm).length, 5);
  assert.ok(chunks > 1, 'the body should arrive in more than one chunk');
});

test('128 requests that wait on I/O are served concurrently by one process', async () => {
  const before = process.cpuUsage();
  const started = performance.now();
  const responses = await Promise.all(Array.from({ length: 128 }, () => fetch(`${base}/api/slow?ms=200`)));
  const wall = (performance.now() - started) / 1000;
  const cpu = cpuSeconds(process.cpuUsage(before));
  assert.ok(responses.every((r) => r.status === 200));
  await Promise.all(responses.map((r) => r.arrayBuffer()));
  // Served one after another this would take 128 x 0.2 s = 25.6 s.
  assert.ok(wall < 3, `expected the batch to overlap, took ${wall.toFixed(2)} s`);
  metrics.ioBound = { requests: 128, waitPerRequestSeconds: 0.2, sumOfRequestDurationsSeconds: 25.6, wallSeconds: Number(wall.toFixed(3)), cpuSeconds: Number(cpu.toFixed(3)) };
});

test('CPU-bound requests are billed for what they burn, and block everything else meanwhile', async () => {
  const before = process.cpuUsage();
  const started = performance.now();
  const work = fetch(`${base}/api/cpu?rounds=400000`);
  await new Promise((resolve) => setTimeout(resolve, 20));
  const healthStarted = performance.now();
  await (await fetch(`${base}/healthz`)).arrayBuffer();
  const healthDelay = (performance.now() - healthStarted) / 1000;
  await (await work).arrayBuffer();
  const wall = (performance.now() - started) / 1000;
  const cpu = cpuSeconds(process.cpuUsage(before));
  assert.ok(cpu > wall * 0.5, 'a hashing loop should keep the CPU busy for most of its duration');
  metrics.cpuBound = { requests: 1, wallSeconds: Number(wall.toFixed(3)), cpuSeconds: Number(cpu.toFixed(3)), healthCheckDelayedBySeconds: Number(healthDelay.toFixed(3)) };
});
