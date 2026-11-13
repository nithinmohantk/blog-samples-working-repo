// An appointments API as an ordinary HTTP server. No Lambda handler, no adapter, no dependencies.
// Lambda Web Functions tell the server where to listen through AWS_LAMBDA_HTTP_ENDPOINT (host:port);
// on a laptop the same variable, or the default below, does the same job.
'use strict';

const http = require('node:http');
const crypto = require('node:crypto');
const { setTimeout: sleep } = require('node:timers/promises');

// Synthetic data. No real patients, clinics or clinicians.
const APPOINTMENTS = [
  { id: 'apt-1001', clinic: 'north', start: '2026-10-19T09:00:00Z', status: 'booked' },
  { id: 'apt-1002', clinic: 'north', start: '2026-10-19T09:30:00Z', status: 'free' },
  { id: 'apt-1003', clinic: 'south', start: '2026-10-19T10:00:00Z', status: 'booked' },
];

// Start-up work that must not delay listening: the platform expects the port to be open within
// ten seconds, and routes requests as soon as it is. Handlers that need the result await it.
let ready;
function warmUp() {
  ready ??= sleep(20).then(() => ({ loadedAt: new Date().toISOString() }));
  return ready;
}

function send(res, status, body, headers = {}) {
  const payload = JSON.stringify(body);
  res.writeHead(status, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(payload), ...headers });
  res.end(payload);
}

// Lambda appends the connecting client's address as the last value. Earlier values are whatever the
// caller sent, so only the last one is trusted.
function clientAddress(req) {
  const forwarded = String(req.headers['x-forwarded-for'] ?? '').split(',').map((part) => part.trim()).filter(Boolean);
  return forwarded.at(-1) ?? req.socket.remoteAddress;
}

async function route(req, res) {
  const url = new URL(req.url, 'http://placeholder');
  const requestId = req.headers['lambda-web-request-id'] ?? crypto.randomUUID();

  if (req.method === 'GET' && url.pathname === '/healthz') {
    return send(res, 200, { status: 'ok' });
  }

  if (req.method === 'GET' && url.pathname === '/api/appointments') {
    await warmUp();
    const clinic = url.searchParams.get('clinic');
    const items = clinic ? APPOINTMENTS.filter((a) => a.clinic === clinic) : APPOINTMENTS;
    return send(res, 200, { items, requestId, client: clientAddress(req) });
  }

  // Stands in for a call to a database or another service: the request waits and uses almost no CPU.
  if (req.method === 'GET' && url.pathname === '/api/slow') {
    const wait = Math.min(Number(url.searchParams.get('ms') ?? 50), 5000);
    await sleep(wait);
    return send(res, 200, { waitedMs: wait, requestId });
  }

  // Stands in for CPU-bound work. In a single-threaded server this blocks every other request.
  if (req.method === 'GET' && url.pathname === '/api/cpu') {
    const rounds = Math.min(Number(url.searchParams.get('rounds') ?? 200000), 2000000);
    let digest = Buffer.alloc(32);
    for (let i = 0; i < rounds; i++) {
      digest = crypto.createHash('sha256').update(digest).digest();
    }
    return send(res, 200, { rounds, digest: digest.toString('hex').slice(0, 16), requestId });
  }

  // Server-sent events: the response is written as it is produced.
  if (req.method === 'GET' && url.pathname === '/events') {
    const count = Math.min(Number(url.searchParams.get('count') ?? 5), 100);
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
    for (let i = 1; i <= count; i++) {
      res.write(`data: ${JSON.stringify({ sequence: i, of: count })}\n\n`);
      await sleep(10);
    }
    return res.end();
  }

  return send(res, 404, { error: 'not found', requestId });
}

function createServer() {
  return http.createServer((req, res) => {
    route(req, res).catch(() => {
      // Never put request content in an error response or a log line.
      if (!res.headersSent) send(res, 500, { error: 'internal error' });
      else res.destroy();
    });
  });
}

function listenAddress() {
  const [host, port] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT || '127.0.0.1:3000').split(':');
  return { host, port: Number(port) };
}

if (require.main === module) {
  const server = createServer();
  const { host, port } = listenAddress();
  server.listen(port, host, () => console.log(JSON.stringify({ event: 'listening', host, port })));
  warmUp();

  // The platform allows about one second after SIGTERM, and does not promise the signal arrives.
  // Flush what is cheap to flush and leave; do not start new work here.
  process.on('SIGTERM', () => {
    console.log(JSON.stringify({ event: 'sigterm' }));
    process.exit(0);
  });
}

module.exports = { createServer, listenAddress };
