FROM lscr.io/linuxserver/baseimage-ubuntu:jammy

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    VIRTUAL_ENV=/app/.venv \
    PATH=/app/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python3 -m venv "$VIRTUAL_ENV" \
    && "$VIRTUAL_ENV/bin/pip" install --upgrade pip \
    && rm -rf /root/.cache/pip

COPY docker/requirements.txt /tmp/production-requirements.txt

RUN "$VIRTUAL_ENV/bin/pip" install --no-cache-dir -r /tmp/production-requirements.txt \
    && rm -f /tmp/production-requirements.txt \
    && rm -rf /root/.cache/pip

COPY app/ /app/app/

RUN mkdir -p /etc/cont-init.d /etc/services.d/harmony

COPY docker/cont-init.d/10-prepare-dirs /etc/cont-init.d/10-prepare-dirs
COPY docker/services.d/harmony/run /etc/services.d/harmony/run

RUN chmod +x /etc/cont-init.d/10-prepare-dirs /etc/services.d/harmony/run

VOLUME ["/config", "/downloads", "/music"]

EXPOSE 8080

CMD ["/init"]
