# CLAUDE.md

Guidance for Claude Code working in this repository. Keep this file updated as the codebase changes.

## What this is
Receptionaly AI — an AI receptionist for clinics that answers patient messages 24/7, books into a real calendar, and reduces no-shows. Channel-agnostic core; **WhatsApp is the only active channel** (SMS/Twilio deferred). Currently a **demo-first** build targeting one US clinic: synthetic patients, no real PHI, consumer Anthropic key acceptable.

## Stack
Django 5 + DRF · Celery + Redis · PostgreSQL 16 · React 18 + Vite + Tailwind · Docker Compose.

## Non-negotiable principles
- **The LLM never owns the calendar.** All scheduling (availability, booking, conflict detection) is deterministic Python in `backend/apps/scheduling/engine.py`. The LLM only converses and calls validated tools. Booking uses a Postgres advisory lock + a live re-check so double-booking is structurally impossible. Slot tokens are opaque base64 the LLM echoes back; the engine re-validates them against live availability (anti-invention guarantee).
- **Channel abstraction.** Core logic sits behind a channel interface; every feature must work over plain text. Only the WhatsApp adapter is wired.
- **`clinic_id` on every table** from day 1 (single-tenant now, multi-tenant-ready for Phase 4).
- **Assistive, never clinical.** No medical advice. An emergency-keyword regex fast-path (`backend/apps/conversations/emergency.py`) bypasses the LLM entirely and escalates.

## Layout
```
backend/    Django project
  apps/clinics/        Clinic + Patient models, TCPA consent fields
  apps/scheduling/     Practitioner/Service/ScheduleRule/Appointment + engine.py (deterministic core)
  apps/conversations/  Conversation/FAQ/EscalationTicket, LLM engine.py, tools.py, prompt.py, emergency.py, inbound.py
  apps/messaging/      Message model, WhatsApp channel adapter, Celery tasks (process_inbound)
  apps/api/            DRF serializers/views/urls for the staff dashboard + seed_demo command
  config/              settings.py, urls.py
frontend/   React dashboard (Vite :5173, proxies /api to Django :8000)
infra/      docker-compose.yml, nginx
prompts/    Versioned LLM system prompts (booking_system_v1.md)
docs/       runbook.md
tests/e2e/  Conversation simulations
```

## Common commands
Compose file lives in `infra/`, so either `cd infra` first or pass `-f infra/docker-compose.yml`.
```bash
# from infra/
docker compose up --build                       # start web/worker/beat/postgres/redis
docker compose exec web python manage.py migrate
docker compose exec web python manage.py test   # backend suite
docker compose exec web python manage.py seed_demo   # seed demo clinic + staff user

# frontend (from frontend/)
npm install
npm run dev      # Vite dev server on :5173
npm run build    # production build
```

## Dev chat sandbox
Until the WhatsApp number is live, test the conversation flow via the **"Chat (test)"** dashboard tab. It posts to `POST /api/dev/chat`, which reuses the real inbound pipeline (patient upsert, consent/STOP, LLM tool loop) but skips the outbound channel send. The endpoint is **DEBUG-gated** (404 in prod) and uses a fixed demo phone `+15550000000`. `GET` returns history, `DELETE` resets (deletes the demo patient + their data). **Every POST is a live Anthropic call** — the UI disables Send while awaiting and never polls; keep it that way to avoid runaway spend. The sandbox is a single shared conversation, so only one person should drive it at a time.

## Conventions & gotchas
- **Prompts must be reachable at `/prompts` inside the container.** `prompt.py` resolves the template to `/prompts/booking_system_v1.md`. The web image is built from `../backend` only, so `prompts/` is bind-mounted (`../prompts:/prompts:ro`) in web/worker/beat. If you move prompts or change the build context, update both.
- **Celery `worker`/`beat` do NOT hot-reload.** Only the `web` container (runserver) auto-reloads on code/prompt changes. After any change that affects a Celery task path (engine, tools, prompt template, inbound pipeline), run `docker compose restart worker beat` — otherwise inbound WhatsApp messages fail silently in the worker while the dev sandbox (which runs in `web`) looks fine. This bit us once: a new `{patient_context}` prompt placeholder crashed the worker with `KeyError` until it was restarted.
- **`anthropic` must be baked into the image** (it's in `requirements.txt`). Don't rely on `pip install` inside a running container — `docker compose up` recreates from the image and loses it. Rebuild (`docker compose build web worker beat`) after dependency changes.
- **Migrations** land on the host via the `../backend:/app` bind mount — generate them in the container, they appear in the tree.
- **CSRF:** the dashboard uses DRF SessionAuthentication + CSRF. `CSRF_TRUSTED_ORIGINS` (settings.py) must include the frontend origin (`http://localhost:5173` in dev; env `DJANGO_CSRF_TRUSTED_ORIGINS` overrides). DRF only enforces CSRF once a session user exists, so login POST passes but later writes fail if the origin isn't trusted.
- **Timezones:** appointments are stored in UTC (`USE_TZ=True`). Clinic-local wall-clock times must be converted using the clinic timezone, not the browser's — see `clinicWallTimeToUTC` in `frontend/src/pages/Calendar.jsx`.
- **API routes:** `DefaultRouter(trailing_slash=False)` — no trailing slashes. `/api/me` (not `/api/auth/me`) returns the current user + clinic. Patients are created by the inbound pipeline, not the dashboard (viewset is read-only for create).
- **US formatting:** 12-hour times in patient-facing output.

## Demo credentials / data
`seed_demo` creates clinic "Bright Smiles Dental", staff login `demo` / `demo12345`, Dr. Rivera, 4 services, Mon–Fri 9–17 hours, 5 FAQs.

## Interactive CTA booking (present_options)
Patients can tap options instead of typing. The `present_options` tool lets the LLM offer a short choice set; the reply is carried as a structured `BotReply` (`conversations/reply.py`) through the channel layer. WhatsApp renders ≤3 options as reply buttons and 4–10 as a list (`whatsapp.py::_interactive_payload`); other channels get a numbered-text fallback. A tap comes back as the option **label**, which the existing `check_availability` + `slot_token` match-and-book flow handles — the LLM still never owns the calendar. The dev sandbox renders the same options as tappable chips (`Chat.jsx`).
- **Known risk:** in a conversation that already has a prior booking in history, the model has once emitted a "confirmed" reply **without** calling `book_appointment` (a false confirmation). Clean conversations book reliably. Candidate guardrail: suppress booking-confirmation language when no `book_appointment` succeeded that turn.

## Testing notes
- Backend: 52 tests. 4 live-Anthropic conversation tests are `skipUnless(ANTHROPIC_API_KEY)`. `ANTHROPIC_API_KEY` is set in `.env` (model `claude-haiku-4-5` — cheap), so these run. Live conversation flow is verified working via the dev chat sandbox and real WhatsApp.

## Phase status
- Phase 0: WhatsApp webhook walking skeleton — committed.
- Phase 1: booking MVP + minimal staff dashboard — built and verified end-to-end (login → calendar → manual booking).
- WhatsApp live integration + interactive CTA booking — built, verified end-to-end, pushed (`f577770`).
- Next: Phase 2 (reminders + schedule management; also reschedule/cancel over chat, plus prod-readiness: CI/CD, monitoring, deploy, ≥25-scenario sim suite, load sanity).
