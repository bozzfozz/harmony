FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

RUN mkdir -p /app/frontend \
    && chown -R node:node /app
USER node

COPY --chown=node:node frontend/package*.json ./
COPY --chown=node:node frontend/.npmrc ./.npmrc
RUN npm ci --no-audit --no-fund

COPY --chown=node:node frontend/ ./
ENV NODE_ENV=production
RUN npm run build

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

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

EXPOSE 8080 8888

# Standard: Production
ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
