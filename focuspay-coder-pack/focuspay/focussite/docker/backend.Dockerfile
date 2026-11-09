FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash postgresql-client fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system --gid 10001 focuspay \
    && adduser --system --uid 10001 --ingroup focuspay --home /nonexistent --shell /usr/sbin/nologin focuspay

WORKDIR /runtime

COPY site/exchange-backend/requirements.txt /tmp/backend-requirements.txt
COPY bot/tg_bot_btc/requirements.txt /tmp/bot-requirements.txt
RUN pip install --no-cache-dir \
      -r /tmp/backend-requirements.txt \
      -r /tmp/bot-requirements.txt \
    && rm -f /tmp/backend-requirements.txt /tmp/bot-requirements.txt

COPY --chown=focuspay:focuspay site/exchange-backend /app/backend
COPY --chown=focuspay:focuspay bot/tg_bot_btc /opt/tg_bot_btc
COPY --chown=focuspay:focuspay test_support /app/test_support
COPY --chown=focuspay:focuspay focussite/docker/run_backend.py /runtime/run_backend.py

RUN mkdir -p /opt/tg_bot_btc/receipts \
      /opt/tg_bot_btc/chat_uploads \
      /opt/tg_bot_btc/bot_user_avatars \
      /opt/tg_bot_btc/operator_avatars \
      /var/log/focuspay \
    && chown -R focuspay:focuspay /opt/tg_bot_btc /var/log/focuspay

USER focuspay
EXPOSE 8000
