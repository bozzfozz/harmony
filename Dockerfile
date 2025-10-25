FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1 \
    APP_PORT=8080 \
    APP_MODULE=app.main:app \
    PUID=1000 \
    PGID=1000

WORKDIR /app

COPY requirements.txt ./

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl build-essential python3-dev \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN chmod +x scripts/docker-entrypoint.sh

EXPOSE 8080

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD []
