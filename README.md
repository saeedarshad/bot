# Receptionaly AI

AI receptionist for clinics — answers patient messages 24/7, books appointments into a real calendar, and reduces no-shows. Channel-agnostic core; **WhatsApp** is the active channel (SMS/Twilio deferred).

## Stack
Django 5 + DRF · Celery + Redis · PostgreSQL 16 · React (dashboard, later) · Docker Compose.

## Local development
```bash
cp .env.example .env        # fill in secrets
cd infra
docker compose up --build
```
- API: http://localhost:8000
- Health check: http://localhost:8000/healthz

Run migrations / management commands:
```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Run tests:
```bash
docker compose exec web python manage.py test
```

## Layout
```
backend/    Django project (apps: clinics, messaging, scheduling, conversations)
frontend/   React dashboard (Phase 1+)
infra/      Docker Compose, nginx, deploy
prompts/    Versioned LLM system prompts + tool defs
docs/       Runbook, onboarding, incident log
tests/e2e/  Conversation simulations
```

## Guardrails (non-negotiable)
- The LLM never owns the calendar — all scheduling is deterministic Python.
- Channel abstraction: every feature must work on plain text.
- `clinic_id` on every table from day 1.
- Assistive, never clinical.
