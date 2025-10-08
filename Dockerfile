FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY --chown=node:node frontend/package*.json ./
USER node
RUN npm ci

COPY --chown=node:node frontend/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .
COPY --from=frontend-builder /app/frontend/dist ./frontend_dist

RUN chmod +x scripts/docker-entrypoint.sh

EXPOSE 8000

# Standard: Production
ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
