#!/usr/bin/env python3
"""Upload FocusPay brand stickers to Telegram via Bot API (run on server or locally with token)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# slug -> emoji
STICKERS = [
    ("01_logo", "🤍"),
    ("02_hi", "👋"),
    ("03_wait", "⏳"),
    ("04_done", "✅"),
    ("05_thanks", "🙏"),
    ("06_pulse", "📈"),
    ("07_promo", "🎁"),
    ("08_check", "🛡"),
    ("09_news", "📣"),
    ("10_help", "🆘"),
    ("11_ok", "👍"),
    ("12_paid", "💳"),
]


def api(token: str, method: str, *, data: dict | None = None, files: dict | None = None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        import uuid

        boundary = "----FocusPay" + uuid.uuid4().hex
        body = bytearray()
        for k, v in (data or {}).items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
            body.extend(str(v).encode())
            body.extend(b"\r\n")
        for k, (filename, content, ctype) in files.items():
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(
                f'Content-Disposition: form-data; name="{k}"; filename="{filename}"\r\n'.encode()
            )
            body.extend(f"Content-Type: {ctype}\r\n\r\n".encode())
            body.extend(content)
            body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())
        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
    else:
        payload = json.dumps(data or {}).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def api_safe(token: str, method: str, *, data: dict | None = None, files: dict | None = None):
    try:
        return api(token, method, data=data, files=files)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "error_code": e.code, "description": str(e)}


def main() -> int:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    user_id = int(os.environ.get("STICKER_OWNER_USER_ID") or "7869431717")
    sticker_dir = Path(os.environ.get("STICKER_DIR") or ".")
    bot_user = (os.environ.get("TELEGRAM_BOT_USERNAME") or "focuspay1_bot").strip().lstrip("@")
    set_name = f"FocusPay_by_{bot_user}"
    title = "FocusPay"

    if not token:
        print("TELEGRAM_BOT_TOKEN required", file=sys.stderr)
        return 1

    def call_json(method: str, data: dict):
        try:
            return api(token, method, data=data)
        except Exception as e:
            # surface Telegram error body
            if hasattr(e, "read"):
                try:
                    return json.loads(e.read().decode())
                except Exception:
                    pass
            raise

    # Check if set already exists
    existing = call_json("getStickerSet", {"name": set_name})
    if existing.get("ok"):
        print(
            f"Set already exists: {set_name} "
            f"({len(existing['result'].get('stickers', []))} stickers)"
        )
        print(f"https://t.me/addstickers/{set_name}")
        return 0
    print(f"getStickerSet (expected if new): {existing.get('description') or existing}")

    file_ids: list[tuple[str, str]] = []
    for slug, emoji in STICKERS:
        path = sticker_dir / f"{slug}.webp"
        if not path.exists():
            print(f"missing {path}", file=sys.stderr)
            return 1
        raw = path.read_bytes()
        try:
            up = api(
                token,
                "uploadStickerFile",
                data={"user_id": str(user_id), "sticker_format": "static"},
                files={"sticker": (f"{slug}.webp", raw, "image/webp")},
            )
        except Exception as e:
            body = ""
            if hasattr(e, "read"):
                try:
                    body = e.read().decode()
                except Exception:
                    body = str(e)
            print("upload failed", body or e, file=sys.stderr)
            return 1
        if not up.get("ok"):
            print("upload failed", up, file=sys.stderr)
            return 1
        fid = up["result"]["file_id"]
        file_ids.append((fid, emoji))
        print(f"uploaded {slug} -> {fid[:24]}…")

    stickers_payload = [
        {"sticker": fid, "format": "static", "emoji_list": [emoji]}
        for fid, emoji in file_ids
    ]
    created = call_json(
        "createNewStickerSet",
        {
            "user_id": user_id,
            "name": set_name,
            "title": title,
            "stickers": stickers_payload,
            "sticker_type": "regular",
        },
    )
    if not created.get("ok"):
        print("createNewStickerSet failed", created, file=sys.stderr)
        return 1
    print(f"OK set={set_name}")
    print(f"https://t.me/addstickers/{set_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
