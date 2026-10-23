# Fuse 1 / Fuse 1+ camera protocol

These observations come from static inspection of PreForm 3.64.1.664 and testing against an owned Fuse 1+ 30W printer. Other firmware versions may differ. No vendor binaries, camera captures, or decompiled source are distributed here.

## Transport

- Plain RFC 6455 WebSocket at `ws://PRINTER_HOST:8084/`.
- The observed endpoint accepted a connection without credentials.
- The client requests a refresh by sending a text message containing exactly one ASCII space (`0x20`). Client WebSocket frames must be masked.
- Startup text can contain metadata such as `{"width":1280,"height":1024,"action":"init"}`. It is not a JPEG and does not complete a frame request.
- Binary messages contain complete JPEG images; observed frames were 1280 by 1024 pixels. Respect WebSocket fragmentation, continuation frames, and ping/pong control frames.

## Refresh timing

PreForm refreshes independently of incoming frames, with a UI request setting of 60 per second. A request does not guarantee a reply or a new captured image. Waiting for each reply before requesting again can stall indefinitely when a refresh produces no reply.

The relay therefore uses an independent refresh sender and a receiver that stores only the newest JPEG. HTTP viewers share that upstream connection. Increasing request frequency above the printer's capture rate does not create extra camera frames. Report measured image arrival FPS separately from request frequency.

## Other camera backend

A separate RTSP/H.264 backend with a `/formstream` path on port 8554 appears in PreForm for other printer families. It was not the camera protocol used by the tested Fuse 1+ 30W.
