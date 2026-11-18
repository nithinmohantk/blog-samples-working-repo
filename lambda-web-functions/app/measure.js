// Measures what a Web Function is billed for. The server runs as its own process, as it does on the
// platform, and its CPU time is read from the operating system, so the load generator is not counted.
// Linux only (reads /proc). Usage: node measure.js [metrics.json]
'use strict';

const { spawn } = require('node:child_process');
const fs = require('node:fs');
const { performance } = require('node:perf_hooks');
const { setTimeout: sleep } = require('node:timers/promises');

const PORT = 38081;
const BASE = `http://127.0.0.1:${PORT}`;
const TICKS_PER_SECOND = 100; // USER_HZ on Linux

function cpuSecondsOf(pid) {
  const fields = fs.readFileSync(`/proc/${pid}/stat`, 'utf8').split(') ')[1].split(' ');
  return (Number(fields[11]) + Number(fields[12])) / TICKS_PER_SECOND; // utime + stime
}

async function measure(pid, work) {
  const cpuBefore = cpuSecondsOf(pid);
  const started = performance.now();
  const requestSeconds = await work();
  return {
    wallSeconds: Number(((performance.now() - started) / 1000).toFixed(2)),
    sumOfRequestDurationsSeconds: Number(requestSeconds.toFixed(2)),
    serverCpuSeconds: Number((cpuSecondsOf(pid) - cpuBefore).toFixed(2)),
  };
}

async function timed(url) {
  const started = performance.now();
  await (await fetch(url)).arrayBuffer();
  return (performance.now() - started) / 1000;
}

async function main() {
  const server = spawn(process.execPath, ['index.js'], { cwd: __dirname, env: { ...process.env, AWS_LAMBDA_HTTP_ENDPOINT: `127.0.0.1:${PORT}` }, stdio: 'ignore' });
  try {
    for (let i = 0; i < 100; i++) {
      try { await timed(`${BASE}/healthz`); break; } catch { await sleep(50); }
    }

    // 1,280 requests that each wait 200 ms on I/O, 128 at a time.
    const ioBound = await measure(server.pid, async () => {
      let total = 0;
      for (let batch = 0; batch < 10; batch++) {
        total += (await Promise.all(Array.from({ length: 128 }, () => timed(`${BASE}/api/slow?ms=200`)))).reduce((a, b) => a + b, 0);
      }
      return total;
    });

    // 20 requests of hashing, one after another.
    const cpuBound = await measure(server.pid, async () => {
      let total = 0;
      for (let i = 0; i < 20; i++) total += await timed(`${BASE}/api/cpu?rounds=200000`);
      return total;
    });

    // One long CPU-bound request, and a health check sent while it is running.
    const long = timed(`${BASE}/api/cpu?rounds=1500000`);
    await sleep(150);
    const healthCheckSeconds = Number((await timed(`${BASE}/healthz`)).toFixed(2));
    const longRequestSeconds = Number((await long).toFixed(2));

    const metrics = { node: process.version, ioBound: { requests: 1280, ...ioBound }, cpuBound: { requests: 20, ...cpuBound }, blocking: { longRequestSeconds, healthCheckSeconds } };
    console.log(JSON.stringify(metrics, null, 2));
    if (process.argv[2]) fs.writeFileSync(process.argv[2], JSON.stringify(metrics, null, 2));
  } finally {
    server.kill('SIGTERM');
  }
}

main().catch((error) => { console.error(error); process.exit(1); });
