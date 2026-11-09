FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN addgroup --system --gid 10001 focuspay \
    && adduser --system --uid 10001 --ingroup focuspay --home /nonexistent --shell /usr/sbin/nologin focuspay

WORKDIR /app

RUN pip install --no-cache-dir \
      "httpx>=0.26.0" \
      "python-dotenv>=1.0.0"

COPY --chown=focuspay:focuspay deployment_smoke_check.py config.py ./

USER focuspay

CMD ["python", "deployment_smoke_check.py"]
