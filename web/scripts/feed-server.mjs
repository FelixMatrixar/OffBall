// A local live feed for testing the client's live path (PRD 15.7, 16.2): streams public/feeds/showcase.jsonl in real
// time over Server-Sent Events and WebSocket, as the overlay feed would arrive from the broadcast crew.
//
//   GET /sse            Server-Sent Events, one contract message per event
//   GET /ws             WebSocket (upgrade), one contract message per text frame
//   GET /showcase.jsonl the whole feed as JSONL, for ?feed=jsonl:
//   Options on /sse and /ws: ?speed=2 plays faster; ?stall=2:4 sends nothing from 2 s to 6 s, then everything queued.
//
// Each connection streams the moment once from its start, then keeps the clock ticking with clock.sync, so a viewer
// holds the last frame without mistaking the quiet for a stall. Open the app with ?feed=sse:http://localhost:8787/sse.
//
// Usage: npm run feed:serve   (or node scripts/feed-server.mjs --port 8787); run npm run feed:export first.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';

const port = Number(process.argv[process.argv.indexOf('--port') + 1] || process.env.PORT || 8787);
const file = new URL('../public/feeds/showcase.jsonl', import.meta.url);
const lines = readFileSync(file, 'utf8').trim().split('\n');
const messages = lines.map((line) => {
  const m = JSON.parse(line);
  const time = m.type === 'frame' ? m.frame.t_ms : m.type === 'overlay.upsert' ? m.overlay.t_start_ms + 500 : m.t_ms;
  return { line, time };
});
const base = Math.min(...messages.map((m) => m.time));
for (const m of messages) m.at = Math.max(0, (m.time - base) / 1000);
messages.sort((a, b) => a.at - b.at);
const matchId = JSON.parse(lines[0]).match_id;

function options(url) {
  const q = new URL(url, 'http://localhost').searchParams;
  const speed = Math.max(0.25, Math.min(60, Number(q.get('speed') ?? 1) || 1));
  const [at, dur] = (q.get('stall') ?? '').split(':').map(Number);
  return { speed, stall: Number.isFinite(at) && Number.isFinite(dur) ? { at, for: dur } : null };
}

/** Sends the moment in real time to one client; returns a function that stops it. */
function stream(send, { speed, stall }) {
  const start = Date.now();
  let i = 0;
  let lastSync = 0;
  const timer = setInterval(() => {
    const elapsed = ((Date.now() - start) / 1000) * speed;
    if (stall && elapsed >= stall.at && elapsed < stall.at + stall.for) return;
    while (i < messages.length && messages[i].at <= elapsed) send(messages[i++].line);
    if (i >= messages.length && elapsed - lastSync >= 1) {
      lastSync = elapsed;
      send(JSON.stringify({ type: 'clock.sync', match_id: matchId, period: 2, t_ms: Math.round(base + elapsed * 1000), speed, server_time: new Date().toISOString() }));
    }
  }, 20);
  return () => clearInterval(timer);
}

const cors = { 'Access-Control-Allow-Origin': '*' };

const server = createServer((req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  if (path === '/sse') {
    res.writeHead(200, { ...cors, 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
    const stop = stream((line) => res.write(`data: ${line}\n\n`), options(req.url));
    req.on('close', stop);
    return;
  }
  if (path === '/showcase.jsonl') {
    res.writeHead(200, { ...cors, 'Content-Type': 'application/x-ndjson' });
    res.end(lines.join('\n') + '\n');
    return;
  }
  res.writeHead(path === '/' ? 200 : 404, { ...cors, 'Content-Type': 'text/plain; charset=utf-8' });
  res.end(`OffBall feed server: ${messages.length} messages for ${matchId}.\nGET /sse, /ws (WebSocket) or /showcase.jsonl. Options: ?speed=2, ?stall=2:4.\n`);
});

// A minimal WebSocket server (RFC 6455): text frames out, close and ping handled.
server.on('upgrade', (req, socket) => {
  if (new URL(req.url, 'http://localhost').pathname !== '/ws' || !req.headers['sec-websocket-key']) return socket.destroy();
  const accept = createHash('sha1').update(`${req.headers['sec-websocket-key']}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest('base64');
  socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${accept}\r\n\r\n`);
  const frame = (opcode, payload) => {
    const len = payload.length;
    const head = len < 126 ? Buffer.from([0x80 | opcode, len]) : len < 65536 ? Buffer.from([0x80 | opcode, 126, len >> 8, len & 255]) : Buffer.concat([Buffer.from([0x80 | opcode, 127]), (() => { const b = Buffer.alloc(8); b.writeBigUInt64BE(BigInt(len)); return b; })()]);
    socket.write(Buffer.concat([head, payload]));
  };
  const stop = stream((line) => frame(0x1, Buffer.from(line)), options(req.url));
  socket.on('data', (buf) => {
    const opcode = buf[0] & 0x0f;
    if (opcode === 0x8) {
      frame(0x8, Buffer.alloc(0));
      socket.end();
    } else if (opcode === 0x9) frame(0xa, Buffer.alloc(0));
  });
  socket.on('close', stop);
  socket.on('error', stop);
});

server.listen(port, () => console.log(`Feed server on http://localhost:${port}: /sse, /ws, /showcase.jsonl (${messages.length} messages)`));
