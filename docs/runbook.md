# Runbook — Receptionaly AI

## Local dev
```bash
cp .env.example .env
cd infra && docker compose up --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```
- Health: http://localhost:8000/healthz
- Admin: http://localhost:8000/admin
- Tests: `docker compose exec web python manage.py test`

## WhatsApp webhook (once Meta approves)
1. Set `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_APP_SECRET`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN` in `.env`.
2. In Meta App → WhatsApp → Configuration, set callback URL to `https://<domain>/webhooks/whatsapp` and the verify token to match.
3. Subscribe to the `messages` field.

## Secrets
- All secrets live in `.env` on the server, never in git.
- Rotation: update `.env`, `docker compose up -d` to restart affected services.

## TODO (later phases)
- Nightly pg_dump backups + restore drill.
- Deploy pipeline (GitHub Actions on tag).
- Sentry + uptime monitor.
