#!/usr/bin/env python3
"""Fuse 1/1+ WebSocket camera to HTTP MJPEG. Python standard library only."""
from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import signal
import socket
import struct
import threading
import time
from urllib.parse import urlsplit

LOG = logging.getLogger("fuse-camera")


@dataclass(frozen=True)
class Settings:
    printer_host: str = "printer.local"
    printer_port: int = 8084
    max_fps: int = 60
    idle_seconds: int = 15
    listen_host: str = "0.0.0.0"
    listen_port: int = 8766

    @classmethod
    def load(cls):
        options = Path("/data/options.json")
        values = json.loads(options.read_text()) if options.is_file() else {}
        for key in cls.__dataclass_fields__:
            env = os.getenv("FUSE_" + key.upper())
            if env is not None:
                values[key] = env if key.endswith("host") else int(env)
        result = cls(**{k: v for k, v in values.items() if k in cls.__dataclass_fields__})
        if not 1 <= result.max_fps <= 60:
            raise ValueError("max_fps must be 1..60")
        if not 1 <= result.printer_port <= 65535 or not 1 <= result.listen_port <= 65535:
            raise ValueError("Invalid port")
        return result


class CameraSocket:
    def __init__(self, settings: Settings):
        self.sock = socket.create_connection((settings.printer_host, settings.printer_port), 8)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(10)
        self.buffer = bytearray()
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET / HTTP/1.1\r\nHost: {settings.printer_host}:{settings.printer_port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        try:
            self.sock.sendall(request.encode("ascii"))
            while b"\r\n\r\n" not in self.buffer:
                self._receive()
                if len(self.buffer) > 65536:
                    raise ValueError("Oversized WebSocket handshake")
            header, tail = self.buffer.split(b"\r\n\r\n", 1)
            self.buffer = bytearray(tail)
            lines = bytes(header).split(b"\r\n")
            headers = {k.lower(): v.strip() for line in lines[1:] for k, v in [line.split(b":", 1)]}
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
            if lines[0].split()[1] != b"101" or headers.get(b"sec-websocket-accept") != expected:
                raise ConnectionError("Printer rejected the WebSocket handshake")
            if headers.get(b"upgrade", b"").lower() != b"websocket":
                raise ConnectionError("Invalid WebSocket upgrade")
        except Exception:
            self.close()
            raise

    def _receive(self):
        data = self.sock.recv(262144)
        if not data:
            raise ConnectionError("Camera connection closed")
        self.buffer.extend(data)

    def read(self, count):
        while len(self.buffer) < count:
            self._receive()
        data = bytes(self.buffer[:count])
        del self.buffer[:count]
        return data

    def send(self, opcode=1, payload=b" "):
        # Requests and control frames fit the short-frame format.
        if len(payload) > 125:
            raise ValueError("Oversized control/request frame")
        mask = os.urandom(4)
        masked = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
        self.sock.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)

    def images(self):
        fragments = bytearray()
        message_opcode = None
        while True:
            first, second = self.read(2)
            if first & 0x70:
                raise ValueError("Unsupported WebSocket extension")
            opcode, final = first & 15, bool(first & 128)
            length = second & 127
            if length == 126:
                length = struct.unpack(">H", self.read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self.read(8))[0]
            if length > 8 * 1024 * 1024 or len(fragments) + length > 8 * 1024 * 1024:
                raise ValueError("Oversized camera message")
            if opcode >= 8 and (not final or length > 125):
                raise ValueError("Invalid control frame")
            if second & 128:
                raise ValueError("Server frames must not be masked")
            payload = self.read(length)
            if opcode == 8:
                raise ConnectionError("Printer closed the camera connection")
            if opcode == 9:
                self.send(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2):
                if message_opcode is not None:
                    raise ValueError("Interrupted fragmented message")
                message_opcode = opcode
            elif opcode != 0 or message_opcode is None:
                raise ValueError("Invalid continuation frame")
            fragments.extend(payload)
            if final:
                data, kind = bytes(fragments), message_opcode
                fragments.clear()
                message_opcode = None
                # Ignore the startup JSON, e.g. {"action":"init", ...}.
                if kind == 2:
                    if not data.startswith(b"\xff\xd8\xff"):
                        raise ValueError("Camera returned a non-JPEG binary message")
                    yield data

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class CameraSource:
    """One camera connection and latest-frame cache shared by all HTTP consumers."""
    def __init__(self, settings):
        self.settings = settings
        self.condition = threading.Condition()
        self.stopped = False
        self.clients = 0
        self.last_use = 0.0
        self.last_frame = 0.0
        self.sequence = 0
        self.image = None
        self.times = deque()
        self.state = "Idle"
        self.connection = None
        self.thread = threading.Thread(target=self._run, daemon=True, name="fuse-camera")
        self.thread.start()

    def subscribe(self):
        with self.condition:
            self.clients += 1
            self.last_use = time.monotonic()
            self.condition.notify_all()

    def unsubscribe(self):
        with self.condition:
            self.clients = max(0, self.clients - 1)
            self.last_use = time.monotonic()
            self.condition.notify_all()

    def frame(self, after=-1, timeout=15):
        deadline = time.monotonic() + timeout
        with self.condition:
            while not self.stopped:
                now = time.monotonic()
                if self.image and self.sequence > after and now - self.last_frame < 3:
                    return self.sequence, self.image
                remaining = deadline - now
                if remaining <= 0:
                    raise TimeoutError(self.state)
                self.condition.wait(remaining)
        raise ConnectionError("Camera relay stopped")

    def status(self):
        with self.condition:
            now = time.monotonic()
            recent = [t for t in self.times if t >= now - 3]
            fps = (len(recent) - 1) / (recent[-1] - recent[0]) if len(recent) > 1 else 0.0
            return {"state": self.state, "fps": round(fps, 2), "frames": self.sequence,
                    "viewers": self.clients, "last_frame_age": round(now - self.last_frame, 2) if self.last_frame else None}

    def _run(self):
        while not self.stopped:
            with self.condition:
                while not self.clients and not self.stopped:
                    self.state = "Idle"
                    self.condition.wait()
                if self.stopped:
                    return
                self.state = "Connecting"
            camera = None
            pump_stop = threading.Event()
            pump = None
            try:
                camera = CameraSocket(self.settings)
                with self.condition:
                    self.connection = camera
                # PreForm's timer polls independently of incoming JPEGs. Some
                # refreshes need no reply; waiting for one can stall the feed.
                def refresh(camera=camera, halt=pump_stop):
                    deadline = time.monotonic()
                    period = 1 / self.settings.max_fps
                    while not halt.wait(max(0, deadline - time.monotonic())):
                        try:
                            camera.send()
                        except OSError:
                            camera.close()
                            return
                        deadline = max(deadline + period, time.monotonic())
                pump = threading.Thread(target=refresh, daemon=True, name="fuse-refresh")
                pump.start()
                LOG.info("Camera connected: %s:%s", self.settings.printer_host, self.settings.printer_port)
                for image in camera.images():
                    with self.condition:
                        if self.stopped or (not self.clients and time.monotonic() - self.last_use >= self.settings.idle_seconds):
                            break
                        now = time.monotonic()
                        self.image, self.last_frame = image, now
                        self.sequence += 1
                        self.times.append(now)
                        while self.times and self.times[0] < now - 3:
                            self.times.popleft()
                        self.state = "Connected"
                        self.condition.notify_all()
            except (OSError, ValueError, ConnectionError) as error:
                with self.condition:
                    self.state = "Reconnecting"
                    self.condition.notify_all()
                if not self.stopped:
                    LOG.warning("Camera disconnected: %s", error)
                    with self.condition:
                        self.condition.wait(timeout=2)
            finally:
                pump_stop.set()
                if camera:
                    camera.close()
                if pump:
                    pump.join(timeout=3)
                with self.condition:
                    self.connection = None

    def stop(self):
        with self.condition:
            self.stopped = True
            camera = self.connection
            self.condition.notify_all()
        if camera:
            camera.close()
        self.thread.join(timeout=3)


PAGE = b'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fuse 1+ camera</title>
<style>:root{color-scheme:dark;font:16px system-ui;background:#10171c;color:#e7eff4}body{max-width:1100px;margin:30px auto;padding:0 24px}h1{font-size:28px}img{width:100%;border-radius:12px}p{color:#a7bac8}a{color:#b5edcf}button{font:inherit;padding:10px;border:1px solid #435865;border-radius:8px;background:#1d2a33;color:inherit;cursor:pointer}</style>
<h1>Fuse 1+ camera</h1><p id="state">Connecting...</p><img id="image" src="/stream" alt="Live Fuse printer camera"><p id="stats"></p><button id="toggle">Disconnect</button> <a href="/snapshot.jpg" download="fuse-camera.jpg">Save snapshot</a>
<script>let playing=true;document.getElementById('toggle').onclick=()=>{playing=!playing;const image=document.getElementById('image');if(playing){image.src='/stream';image.hidden=false;}else{image.removeAttribute('src');image.hidden=true;}document.getElementById('toggle').textContent=playing?'Disconnect':'Connect';};setInterval(async()=>{try{const r=await(await fetch('/health')).json();document.getElementById('state').textContent=playing?r.state:'Disconnected';document.getElementById('stats').textContent=r.fps.toFixed(1)+' FPS received | '+r.frames+' images received';}catch(e){document.getElementById('state').textContent='Relay disconnected';}},1000);</script></html>'''


def make_server(source, address):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            route = urlsplit(self.path).path
            if route == "/":
                self.reply(200, "text/html; charset=utf-8", PAGE)
            elif route == "/health":
                self.reply(200, "application/json", json.dumps(source.status()).encode())
            elif route in ("/snapshot.jpg", "/stream"):
                source.subscribe()
                started = False
                try:
                    sequence, image = source.frame()
                    if route == "/snapshot.jpg":
                        self.reply(200, "image/jpeg", image)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=fuseframe")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    started = True
                    self.close_connection = True
                    self.connection.settimeout(10)
                    while True:
                        header = f"--fuseframe\r\nContent-Type: image/jpeg\r\nContent-Length: {len(image)}\r\n\r\n".encode()
                        self.wfile.write(header + image + b"\r\n")
                        self.wfile.flush()
                        sequence, image = source.frame(after=sequence)
                except (OSError, TimeoutError, ConnectionError):
                    if not started:
                        try:
                            self.reply(503, "text/plain", b"Camera unavailable; retry shortly.")
                        except OSError:
                            pass
                finally:
                    source.unsubscribe()
            else:
                self.reply(404, "text/plain", b"Not found")

        def reply(self, code, kind, body):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.load()
    source = CameraSource(settings)
    server = make_server(source, (settings.listen_host, settings.listen_port))
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    LOG.info("HTTP relay listening on %s:%s", settings.listen_host, settings.listen_port)
    try:
        server.serve_forever()
    finally:
        source.stop()
        server.server_close()


if __name__ == "__main__":
    main()
