'use strict';
// Node.js 22+; no packages required. Listen only on the local computer.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const sessions = new Map();
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1:8766');
  res.setHeader('Cache-Control', 'no-store');
  if (url.pathname === '/' || url.pathname === '/fuse-camera-live.html') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end(fs.readFileSync(path.join(__dirname, 'fuse-camera-live.html'))); return;
  }
  if (url.pathname === '/stats') {
    const s = sessions.get(url.searchParams.get('id'));
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify(s ? {frames:s.frames, fps:s.fps, state:s.state} : {frames:0, fps:0, state:'Waiting for camera…'})); return;
  }
  if (url.pathname !== '/stream') { res.writeHead(404); res.end(); return; }
  const host = url.searchParams.get('host') || '';
  const id = url.searchParams.get('id') || '';
  if (!/^[a-zA-Z0-9.-]{1,253}$/.test(host) || !/^[a-zA-Z0-9-]{1,80}$/.test(id) || sessions.has(id)) {
    res.writeHead(400); res.end('Invalid camera address or session.'); return;
  }
  let camera;
  try { camera = new WebSocket(`ws://${host}:8084/`); } catch (_) { res.writeHead(400); res.end(); return; }
  camera.binaryType = 'arraybuffer';
  const state = {frames:0, fps:0, state:'Connecting…'}, times = [];
  sessions.set(id, state);
  res.writeHead(200, {'Content-Type':'multipart/x-mixed-replace; boundary=fuseframe', 'X-Content-Type-Options':'nosniff'});
  res.flushHeaders();
  let closed = false, watchdog;
  function close() {
    if (closed) return; closed = true; clearTimeout(watchdog); camera.close(); sessions.delete(id); res.end();
  }
  function request() {
    if (closed || camera.readyState !== WebSocket.OPEN) return;
    camera.send(' '); clearTimeout(watchdog);
    watchdog = setTimeout(() => { state.state = 'Camera stopped replying.'; close(); }, 10000);
  }
  watchdog = setTimeout(close, 10000);
  // Keep a two-request pipeline to overlap network transfer without flooding the camera.
  camera.addEventListener('open', () => { state.state = 'Waiting for camera image…'; request(); request(); });
  camera.addEventListener('message', event => {
    if (closed || typeof event.data === 'string') return;
    const image = Buffer.from(event.data);
    if (image[0] !== 255 || image[1] !== 216 || image[2] !== 255) return;
    clearTimeout(watchdog);
    const now = performance.now(); times.push(now); while (times.length && times[0] < now - 3000) times.shift();
    state.frames++; state.fps = times.length > 1 ? (times.length - 1) * 1000 / (now - times[0]) : 0; state.state = 'Camera connected.';
    const part = Buffer.concat([Buffer.from(`--fuseframe\r\nContent-Type: image/jpeg\r\nContent-Length: ${image.length}\r\n\r\n`), image, Buffer.from('\r\n')]);
    if (res.write(part)) request(); else res.once('drain', request);
  });
  camera.addEventListener('error', close); camera.addEventListener('close', close); res.on('close', close);
});
server.listen(8766, '127.0.0.1', () => console.log('Fuse camera live viewer: http://127.0.0.1:8766/'));
server.on('error', error => { console.error(error.message); process.exitCode = 1; });
