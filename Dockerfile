FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY --chown=node:node frontend/package*.json ./
USER node
RUN npm ci --no-audit --no-fund

COPY --chown=node:node frontend/ ./
ENV NODE_ENV=production
RUN npm run build

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL="postgresql+psycopg://harmony:harmony@postgres:5432/harmony?sslmode=prefer" \
    POSTGRES_HOST=postgres \
    POSTGRES_PORT=5432 \
    POSTGRES_DB=harmony \
    POSTGRES_USER=harmony \
    POSTGRES_PASSWORD=harmony \
    DATABASE_SSLMODE=prefer

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .
COPY --from=frontend-builder /app/frontend/dist ./frontend_dist

RUN chmod +x scripts/docker-entrypoint.sh scripts/db/*.sh

EXPOSE 8080

# Standard: Production
ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
