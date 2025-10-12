FROM node:20.17.1-alpine AS frontend-builder

ENV NPM_CONFIG_REGISTRY=https://registry.npmjs.org/ \
    npm_config_registry=https://registry.npmjs.org/ \
    NPM_CONFIG_PRODUCTION=false \
    npm_config_production=false \
    TOOLCHAIN_STRICT=true \
    SUPPLY_MODE=STRICT

RUN apk add --no-cache bash coreutils jq

WORKDIR /app

COPY . .

RUN npm install -g "npm@$(tr -d '\r\n' < frontend/.npm-version)" \
    && chmod +x scripts/dev/*.sh \
    && chown -R node:node /app

USER node

RUN bash scripts/dev/supply_guard.sh
RUN SUPPLY_GUARD_RAN=1 bash scripts/dev/fe_install_verify.sh

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1 \
    NODE_ENV=production

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .
COPY --from=frontend-builder /app/frontend/dist ./frontend_dist

RUN chmod +x scripts/docker-entrypoint.sh

EXPOSE 8080 8888

# Standard: Production
ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
