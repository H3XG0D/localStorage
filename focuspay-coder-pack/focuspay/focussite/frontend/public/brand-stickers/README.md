# FocusPay brand stickers

Public Telegram sticker pack for buyers / news / support chat.

- **Add pack:** https://t.me/addstickers/FocusPay_by_focuspay1_bot
- **Set name:** `FocusPay_by_focuspay1_bot`
- **Assets:** `*.webp` in this folder (512×512, monochrome F + cosmic bg)

Regenerate locally:

```bash
convert -background none -resize 280x280 focussite/frontend/public/focuspay-logo.svg /tmp/focuspay-f.png
python3 scripts/generate_brand_stickers.py
```

Upload (server, needs bot token + owner who has opened the bot):

```bash
STICKER_DIR=focussite/frontend/public/brand-stickers \
STICKER_OWNER_USER_ID=7869431717 \
TELEGRAM_BOT_USERNAME=focuspay1_bot \
TELEGRAM_BOT_TOKEN=… \
python3 scripts/upload_brand_stickers.py
```

Global allowlist for operator → buyer chat: `OPERATOR_STICKER_SETS=FocusPay_by_focuspay1_bot`
