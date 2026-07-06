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
- **False-confirmation guardrail (built).** The model was observed telling patients an appointment was booked/moved/cancelled without calling the tool that performs it (seen repeatedly on reschedule). `conversations/engine.py` now tracks which mutating tools actually succeeded that turn (`_record_success`) and scans the outgoing reply for confirmation phrasing (`_false_confirmation`). If the reply claims a book/reschedule/cancel that didn't succeed, the model gets one forced correction turn to actually call the tool; if it still fakes it, the turn escalates to a human and sends the safe fallback — a fake confirmation can never reach the patient. Tune the regexes in `_CONFIRM_PATTERNS` if wording drifts.

## Testing notes
- Backend: 82 tests (incl. 13 reminder tests: reconcile idempotency, quiet-hours deferral, cancel-skips, dispatch idempotency/failure-retry). 6 live-Anthropic conversation tests are `skipUnless(ANTHROPIC_API_KEY)` — including `test_full_reschedule_flow_moves_appointment` / `test_full_cancel_flow_cancels_appointment`, which assert the DB actually changed (guarding against the model faking a confirmation without calling the tool). `ANTHROPIC_API_KEY` is set in `.env` (model `claude-haiku-4-5` — cheap), so these run. Live conversation flow is verified working via the dev chat sandbox and real WhatsApp.

## Phase status
- Phase 0: WhatsApp webhook walking skeleton — committed.
- Phase 1: booking MVP + minimal staff dashboard — built and verified end-to-end (login → calendar → manual booking).
- WhatsApp live integration + interactive CTA booking — built, verified end-to-end, pushed (`f577770`).
- Phase 2 (in progress):
  - Reschedule/cancel over chat — built and verified end-to-end (real inbound pipeline, multi-turn). `reschedule_slot` + `cancel_appointment` in `scheduling/engine.py`; `reschedule_appointment`/`cancel_appointment` LLM tools in `conversations/tools.py`; prompt section added. Reschedule is atomic (new slot committed before old is freed, in one transaction; availability excludes the appointment being moved). Ships with the false-confirmation guardrail (see the "Interactive CTA booking" section) that fixed the model faking reschedule confirmations.
  - Reminders / business-initiated messaging (outbox) — built, backend-tested (not yet exercised over live WhatsApp). See "Reminders architecture" below.
  - Appointment lifecycle — `mark_no_show` / `mark_completed` engine fns (no-show bumps `Patient.no_show_count`), exposed as `POST /api/appointments/{id}/no_show|complete`. Patient confirmation (`patient_confirmed_at`) recorded on Confirm tap / `C` reply; at-risk flag (`AppointmentSerializer.at_risk`) surfaces upcoming appts whose 24h reminder went out but the patient never confirmed. Post-appointment auto-complete + thank-you: `finalize_past_appointments` beat task (hourly) completes appts whose whole clinic-local day has ended and queues a `thank_you` outbox row (survives reconcile; gated on `reminders_enabled`).
- Next: Phase 2 remainder (dashboard schedule management: Today view, cost tracker, owner digest; interactive Confirm/Reschedule/Cancel buttons on the 24h reminder are built in the outbox but need Meta-approved templates for live sends), plus prod-readiness: CI/CD, monitoring, deploy, ≥25-scenario sim suite, load sanity.
  - **External dependency:** real business-initiated WhatsApp sends outside the 24h customer-service window require Meta-approved message templates. The `send_template` seam (`channels/base.py`) currently falls back to plain text for the demo; wire actual templates before production.

## Reminders architecture (outbox + beat dispatch)
- **Outbox model** `messaging.ScheduledMessage`: one row per (appointment, kind) — `UNIQUE(appointment, kind)` makes idempotency structural (a reminder can exist at most once, so it can never double-send). Kinds: `confirmation` (due now), `reminder_24h`, `reminder_2h`, `thank_you` (post-visit). The first three are *pre-appointment* (`reminders._PRE_APPOINTMENT_KINDS`) and are the only ones a reconcile marks `skipped` when the appointment leaves an active state — so completing an appointment never skips its own thank-you.
- **Reconciliation is signal-driven** so `scheduling` stays free of any messaging import: a `post_save` on `Appointment` (wired in `messaging/apps.py::ready`) calls `reconcile_appointment_reminders` (`messaging/reminders.py`). Active appointment → confirmation + still-future reminders exist (get_or_create); cancelled/rescheduled/completed/no_show → its unsent rows are marked `skipped`. Reminders whose send time already passed (e.g. a booking made <24h out) are skipped, never back-dated. Gated by `clinic.reminders_enabled`.
- **Dispatch** `messaging/tasks.py::dispatch_due_messages` runs on Celery beat every 5 min (`CELERY_BEAT_SCHEDULE` in settings). Claims due `pending` rows under `select_for_update(skip_locked=True)` so parallel workers never double-send and a crashed worker leaves the row `pending` for retry. Sends via `channel.send_template` (text fallback for demo) and logs an outbound `Message`. Failures keep the row `pending` (→ `failed` after 5 attempts).
- **TCPA quiet hours** (`clinic.quiet_hours_start/end`, clinic-local): a row due outside the window is deferred — its `scheduled_for` is pushed to the next window open, never dropped. Logic in `reminders.py::next_send_time` (handles same-day and overnight windows).
- **Reminder bodies are PHI-minimal** (`build_body`): date/time/clinic only, never procedure details.
- **Message cost estimate** (`messaging/costs.py` + `MessageRate` table): outbound messages snapshot a `category` (WhatsApp conversation category — reminders are `utility`, in-session replies `service`/free) and a `cost_amount` at send time, so a later rate change never rewrites history. Default per-message rates are seeded by migration `0008` (utility $0.04, marketing $0.0625, auth $0.0135, service $0). `GET /api/costs?from=&to=` (default current month) returns total + per-category breakdown for the clinic. Estimate only — real WhatsApp billing is per-conversation.
- **Auto-complete** `messaging/tasks.py::finalize_past_appointments` (beat, hourly): per active clinic, completes still-active appointments whose `ends_at` is before the clinic-local start of *today* (a full-day grace so staff can mark no-show), via `mark_completed` (which fires the reconcile signal → skips pending pre-appointment reminders), then queues a `thank_you` row when `reminders_enabled`. Idempotent via `get_or_create` on the unique (appointment, kind).
- **Owner digest** `messaging/tasks.py::send_owner_digests` (beat, hourly): once-a-day morning summary to `clinic.owner_phone_e164` (blank disables it). Sends when clinic-local hour is in `[owner_digest_hour, 12)` — the window gives a failed 8am send room to retry the same morning. Idempotent via `messaging.OwnerDigest` UNIQUE(clinic, date) (get_or_create claims the day; a send failure deletes the claim so a later run retries). Body built in `messaging/digest.py::build_owner_digest` (total appts, first arrival, at-risk count) — text-only, goes to the business, never a patient.
