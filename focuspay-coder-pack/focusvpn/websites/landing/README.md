# Sideload download site (Launch-L1)

Static page for closed testers. After `FOCUSVPN_API_BASE=… make release-all`:

```bash
mkdir -p websites/landing/downloads
cp -a dist/android websites/landing/downloads/ 2>/dev/null || true
cp -a dist/windows websites/landing/downloads/
cp -a dist/linux websites/landing/downloads/
cd websites/landing && python3 -m http.server 8088
```

Or sync `websites/landing/` to any static host / Caddy `file_server`.

Do not commit real APK/exe binaries to git (see root `.gitignore` `dist/`).
