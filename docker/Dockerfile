FROM ghcr.io/linuxserver/baseimage-ubuntu:jammy

ARG BUILD_DATE
ARG VCS_REF
LABEL org.opencontainers.image.title="harmony" \
      org.opencontainers.image.source="https://github.com/bozzfozz/harmony" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.created="${BUILD_DATE}"

RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-venv python3-pip && \
    rm -rf /var/lib/apt/lists/*

ENV APP_DIR=/app \
    CONFIG_DIR=/config \
    DOWNLOADS_DIR=/downloads \
    MUSIC_DIR=/music

WORKDIR ${APP_DIR}
RUN mkdir -p ${CONFIG_DIR} ${DOWNLOADS_DIR} ${MUSIC_DIR}

COPY app ${APP_DIR}/app

RUN python3 -m venv ${APP_DIR}/.venv && \
    ${APP_DIR}/.venv/bin/pip install --no-cache-dir --upgrade pip && \
    ${APP_DIR}/.venv/bin/pip install --no-cache-dir fastapi uvicorn[standard] httpx "sqlalchemy>=2.0.31,<2.1" aiosqlite aiohttp spotipy mutagen prometheus-client Unidecode

COPY docker/services.d/harmony/run /etc/services.d/harmony/run
COPY docker/cont-init.d/10-prepare-dirs /etc/cont-init.d/10-prepare-dirs
RUN chmod +x /etc/services.d/harmony/run /etc/cont-init.d/10-prepare-dirs

ENV APP_HOST=0.0.0.0 \
    APP_PORT=8080 \
    APP_MODULE=app.main:app \
    UVICORN_EXTRA_ARGS=""

EXPOSE 8080
CMD ["/init"]
