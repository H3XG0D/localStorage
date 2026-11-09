FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system --gid 10001 focuspay \
    && adduser --system --uid 10001 --ingroup focuspay --home /nonexistent --shell /usr/sbin/nologin focuspay

WORKDIR /app

COPY site/exchange-backend/requirements.txt /tmp/requirements.txt
COPY site/exchange-backend/requirements.txt /tmp/backend-requirements.txt
COPY site/exchange-backend/requirements-dev.txt /tmp/backend-dev-requirements.txt
COPY bot/tg_bot_btc/requirements.txt /tmp/bot-requirements.txt
RUN pip install --no-cache-dir \
      -r /tmp/backend-requirements.txt \
      -r /tmp/backend-dev-requirements.txt \
      -r /tmp/bot-requirements.txt \
      asyncpg \
    && rm -f /tmp/requirements.txt /tmp/backend-requirements.txt /tmp/backend-dev-requirements.txt /tmp/bot-requirements.txt

COPY --chown=focuspay:focuspay site/exchange-backend /app/site/exchange-backend
COPY --chown=focuspay:focuspay bot/tg_bot_btc /app/bot/tg_bot_btc
COPY --chown=focuspay:focuspay test_support /app/test_support
COPY --chown=focuspay:focuspay focussite/docker/staging-db /app/focussite/docker/staging-db

USER focuspay
