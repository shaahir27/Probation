# syntax=docker/dockerfile:1
FROM node:20-bookworm-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_PROFILE=synthetic \
    CLOCK_MODE=live \
    PROBATION_DEMO_ALLOW_ANY_HOST=1 \
    PROBATION_DEMO_LOGIN=1 \
    DB_PATH=/data/db/probation.db \
    WORLD_DB_PATH=/data/synth/world.db \
    PROBATION_GMAIL_STORE=/data/private/connectors/gmail_metadata.db \
    PROBATION_ACCOUNTS_DB=/data/private/accounts/accounts.db \
    PROBATION_GMAIL_OWNER_API_KEY=synthetic-demo-owner-key \
    PROBATION_GMAIL_OWNER_ID=local-owner
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl cron \
    && rm -rf /var/lib/apt/lists/*
COPY backend/ ./backend/
RUN pip install --no-cache-dir ./backend
COPY --from=ui /ui/dist ./frontend/dist
COPY config/ ./config/
COPY scripts/ ./scripts/
COPY demo/ ./demo/
RUN chmod +x /app/scripts/demo_reset.sh \
    && printf '0 */6 * * * root APP_PROFILE=synthetic CLOCK_MODE=live DB_PATH=/data/db/probation.db PROBATION_GMAIL_STORE=/data/private/connectors/gmail_metadata.db /bin/sh /app/scripts/demo_reset.sh >> /var/log/probation-reset.log 2>&1\n' > /etc/cron.d/probation-reset \
    && chmod 0644 /etc/cron.d/probation-reset \
    && touch /var/log/probation-reset.log \
    && mkdir -p /data/db /data/synth /data/private/connectors
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1
CMD ["python", "scripts/demo_boot.py"]
