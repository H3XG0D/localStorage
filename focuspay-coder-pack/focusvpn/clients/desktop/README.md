# FocusVPN desktop (P3-M2)

Linux GUI (`focusvpn-gui`) uses the same screens as Android. Login is Telegram or a bot code. The tunnel is VLESS via an `xray` process (Russian names and prefixes stay on the machine's own IP). The headless CLI `focusvpn-desktop` stays on AmneziaWG for `make smoke-desktop`.

## Layout

| Path | Role |
|---|---|
| `frontend/` | Auth / Home / Locations / Account (same layout as Android) |
| `ui/theme.css` | Design tokens (same as frontend) |
| `app/` | Wails bindings over AppCore |
| `cmd/focusvpn-desktop` | Headless CLI (smoke / CI) |
| `cmd/focusvpn-gui` | Wails window (`-tags wails`) |

## Run GUI (needs webkit2gtk)

```bash
# Debian/Ubuntu: libgtk-3-dev libwebkit2gtk-4.1-dev
go build -tags wails -o bin/focusvpn-gui ./clients/desktop/cmd/focusvpn-gui
./bin/focusvpn-gui
# dev: --api http://localhost:8080 --dry-run
```

## Smoke (no webkit)

```bash
make smoke-desktop
```

## Preview в браузере (без Wails/webkit)

`frontend/preview.js` — мок `window.go.app.App` (Status, ListServers с пингом/нагрузкой, Connect/Disconnect с задержками). В прод-сборке Wails настоящий runtime перекрывает мок.

```bash
cd clients/desktop/frontend
python3 -m http.server 8901
# http://localhost:8901/index.html
```
