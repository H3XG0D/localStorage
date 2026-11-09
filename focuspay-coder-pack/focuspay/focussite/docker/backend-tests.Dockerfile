FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTEST_ADDOPTS="-p no:cacheprovider"

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash postgresql-client \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system --gid 10001 focuspay \
    && adduser --system --uid 10001 --ingroup focuspay --home /nonexistent --shell /usr/sbin/nologin focuspay

COPY site/exchange-backend/requirements.txt /tmp/pip-dev/requirements.txt
COPY site/exchange-backend/requirements-dev.txt /tmp/pip-dev/requirements-dev.txt
COPY bot/tg_bot_btc/requirements.txt /tmp/bot-requirements.txt
RUN pip install --no-cache-dir \
      -r /tmp/pip-dev/requirements-dev.txt \
      -r /tmp/bot-requirements.txt \
    && rm -rf /tmp/pip-dev /tmp/bot-requirements.txt

WORKDIR /opt/focuspay/site/exchange-backend

USER focuspay
