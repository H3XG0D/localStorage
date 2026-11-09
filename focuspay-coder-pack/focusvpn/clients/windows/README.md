# FocusVPN Windows (P3-M5b bridge)

GUI uses the same screens as Android ([`clients/desktop/frontend`](../desktop/frontend)): Telegram or code, VLESS through an `xray` process. Place `wintun.dll` next to the GUI exe. The headless CLI stays on **amneziawg-go** so `make smoke-windows` does not change.

## Layout

| Path | Role |
|---|---|
| `app/` | AppCore bindings (`platform=windows`) |
| `engine/` | `WintunEngine` → probes `wintun.dll`, dataplane = AppCore `GoEngine` |
| `storage/` | DPAPI on Windows; envelope + file 0600 elsewhere |
| `cmd/focusvpn-windows` | Headless CLI (`make smoke-windows`) |
| `cmd/focusvpn-windows-gui` | Wails GUI (`-tags wails`) |

## Run

```bash
make windows-check
make smoke-windows

# GUI (needs WebView2 on Windows / webkit on Linux)
go build -tags wails -o bin/focusvpn-windows-gui ./clients/windows/cmd/focusvpn-windows-gui
./bin/focusvpn-windows-gui
# dev: --api http://localhost:8080 --dry-run
```

### Real tunnel (Windows, elevated)

1. Place prebuilt `wintun.dll` next to the EXE.
2. Run without `--dry-run` (admin usually required for the adapter).
3. Optional: `FOCUSVPN_ENGINE=wireguard|xray` for other AppCore engines.

## wintun.dll

Ship the **prebuilt** `wintun.dll` next to the EXE (WireGuard LLC Prebuilt Binaries License).
Do **not** statically link GPL wintun sources. AmneziaWG userspace is **amneziawg-go** `v0.2.19`
(`CreateTUN` loads wintun at runtime).

## Non-negotiables

- Private keys: DPAPI (`CryptProtectData`) on Windows
- No GPL in the product binary
- Pin amneziawg-go `v0.2.19`
