# Home Assistant app

Camera integration by **[byfuse3d.com](https://byfuse3d.com/)**.

[![Add repository to Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Fbyfuse3d%2Fformlabs-fuse-camera)

The button opens Home Assistant with this app repository prefilled. Confirm adding the repository, then install **Formlabs Fuse Camera by byfuse3d.com**. Home Assistant OS is required for the app store.

1. Make this source available to your Home Assistant installation. Add `https://github.com/byfuse3d/formlabs-fuse-camera` in the app store repository settings; alternatively, copy the `formlabs_fuse_camera` directory into Home Assistant's local apps directory using existing administrative access.
2. Install **Formlabs Fuse Camera by byfuse3d.com** from the app store and open its Configuration page.
3. Set `printer_host` to the printer's local address or hostname. `printer.local` is a placeholder and may not resolve on your network.
4. Keep `printer_port` at `8084`, `max_fps` at `60`, and `idle_seconds` at `15` unless you need to tune them.
5. Start the app and enable **Start on boot**.
6. Add the **MJPEG IP Camera** integration. Set the stream URL to `http://homeassistant.local:8766/stream` and the still image URL to `http://homeassistant.local:8766/snapshot.jpg`, replacing the hostname if needed. Leave credentials empty.
7. Add a picture entity card for the newly created camera entity. See `dashboard-card.yaml` and adjust its entity ID to match your installation.

The preview is at `http://homeassistant.local:8766/`. Camera acquisition starts when a stream or snapshot is requested. Reading `/health` alone does not open the camera.

The app supports `amd64` and `aarch64`. It serves HTTP on port `8766` and connects to the printer on port `8084`. Printer settings remain local to the Home Assistant installation.

## Environment variables

Outside Home Assistant, `FUSE_PRINTER_HOST`, `FUSE_PRINTER_PORT`, `FUSE_MAX_FPS`, `FUSE_IDLE_SECONDS`, `FUSE_LISTEN_HOST`, and `FUSE_LISTEN_PORT` override defaults. On Home Assistant, values are loaded from `/data/options.json`; environment variables take precedence.

## Troubleshooting

- Check `/health` while a stream is open. `fps` measures received images, not requests.
- Verify the relay host can reach the printer's camera port.
- If the feed freezes with an older prototype, use version 1.0.1 or newer: requests must continue even when some requests have no reply.
- If the feed is slow, run the relay on the same LAN as the printer and check competing camera clients.
- The Fuse 1+ backend uses WebSocket/JPEG. The separate RTSP backend found in PreForm belongs to other printer families.
