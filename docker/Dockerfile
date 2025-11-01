FROM lscr.io/linuxserver/baseimage-alpine:3.19

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apk add --no-cache python3 py3-pip curl \
    && apk add --no-cache --virtual .build-deps gcc musl-dev python3-dev libffi-dev

WORKDIR /app

RUN python3 -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip

COPY docker/requirements.txt /tmp/requirements.txt

RUN /app/.venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -rf /root/.cache/pip \
    && apk del .build-deps

COPY app/ /app/app/

RUN mkdir -p /etc/services.d/harmony /config /downloads /music \
    && chown -R abc:abc /app

COPY docker/services.d/harmony/run /etc/services.d/harmony/run
RUN chmod +x /etc/services.d/harmony/run

VOLUME ["/config", "/downloads", "/music"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 CMD curl -fsS http://localhost:8080/live || exit 1
