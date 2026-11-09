FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CHROME_PATH=/usr/bin/chromium

# Profile banners are rendered by headless Chromium inside the bot container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        fonts-dejavu \
        fonts-noto-color-emoji \
        fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system --gid 10001 focuspay \
    && adduser --system --uid 10001 --ingroup focuspay --home /nonexistent --shell /usr/sbin/nologin focuspay

WORKDIR /opt/tg_bot_btc

COPY bot/tg_bot_btc/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY --chown=focuspay:focuspay bot/tg_bot_btc /opt/tg_bot_btc

RUN mkdir -p /opt/tg_bot_btc/receipts \
      /opt/tg_bot_btc/chat_uploads \
      /opt/tg_bot_btc/data \
      /opt/tg_bot_btc/bot_user_avatars \
      /opt/tg_bot_btc/operator_avatars \
    && chown -R focuspay:focuspay /opt/tg_bot_btc

USER focuspay
EXPOSE 8082
