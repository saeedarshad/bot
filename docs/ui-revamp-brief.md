# Complete Professional UI Revamp — Receptionaly AI

## Orientation (read first)
You're working on **Receptionaly AI**, a WhatsApp AI receptionist for dental/medical
clinics. **Read `CLAUDE.md` at the repo root before starting** — it has the full
architecture, phase history, and conventions. Backend is Django 5 + DRF (Docker
Compose in `infra/`), already feature-complete through Phase 4 (multi-tenant, 262
tests green). This task is **frontend only** — a complete professional redesign of
the dashboard. Do NOT change backend behavior, models, or API contracts.

## The goal
Turn the current bare-bones functional dashboard into a polished, modern SaaS product
that looks like software with tens of thousands of users. Specifically:
- A beautiful, professional **login page**.
- A **full professional staff dashboard** (the clinic-facing side).
- A **full professional operator/admin console** (the superuser side) — equally polished.
- Smooth **animations & micro-interactions**, an **interactive, easy-to-navigate** IA,
  responsive down to mobile, accessible (keyboard + screen-reader friendly), and a
  cohesive design system (typography, color, spacing, elevation, motion).
- Support **light mode** (and dark mode if low-cost). Consistent empty/loading/error states.

## Current frontend (what exists — preserve the behavior, redesign the surface)
- Stack: **React 18 + Vite + Tailwind CSS 3**. No router, no component library, no icon
  set, no animation lib yet. Only deps are react/react-dom. Tailwind config is empty
  (`theme.extend` unused) — build the design system here (tokens, fonts, colors).
- `frontend/src/main.jsx` → renders `<App/>`. `frontend/src/index.css` = Tailwind entry.
- `frontend/src/App.jsx` — the shell: fetches `/api/me`, shows `<Login>` if unauthed,
  routes **superusers** to `<Operator/>`, everyone else to a **tab-based** staff dashboard.
  Tabs: Calendar, Analytics, Recalls, Chat (test), Patients, Escalations, Settings.
- `frontend/src/api.js` — `api(path, {method, body})` fetch wrapper (session cookie +
  CSRF header via `X-CSRFToken`) and `ensureCsrf()`. **Keep this contract**; auth is DRF
  SessionAuthentication + CSRF, same-origin via Vite proxy (`/api` → :8000).
- Pages (`frontend/src/pages/`): `Login.jsx`, `Calendar.jsx` (today view + month calendar,
  lifecycle buttons, cost pill), `Analytics.jsx` (recovered-revenue headline, stat cards,
  no-show trend, bookings-by-source bars, monthly report viewer), `Recalls.jsx` (rules +
  preview/run + campaign history), `Patients.jsx`, `Escalations.jsx`, `Settings.jsx`,
  `Chat.jsx` (dev sandbox), `Operator.jsx` (clinics table, create-clinic form, per-clinic
  subscription editor, staff mgmt, delete).

## API surface you'll render (all under `/api`, session-auth, no trailing slash)
- `GET /me` → `{username, is_superuser, clinic}`; `POST /auth/login`, `POST /auth/logout`,
  `GET /auth/csrf`.
- Staff: `appointments` (+ `/{id}/no_show`, `/{id}/complete`), `patients`
  (+ `/{id}/messages`), `services`, `practitioners`, `schedule-rules`,
  `schedule-exceptions`, `faqs`, `escalations` (+ `/{id}/resolve`),
  `conversations/{id}/messages`, `recall-rules` (+ `/{id}/preview`, `/{id}/run`),
  `recall-campaigns`, `costs`, `analytics`, `reports/monthly`, `quality/export`,
  `settings`, `dev/chat`.
- Operator (superuser only): `admin/clinics` (GET/POST/DELETE),
  `admin/clinics/{id}/subscription` (PATCH), `admin/clinics/{id}/staff` (GET/POST).
Inspect `backend/apps/api/serializers.py` + `operator.py` for exact field shapes.

## How to run + verify
- Backend + DB are in Docker: `docker compose -f infra/docker-compose.yml up` (Django on
  :8000). Frontend: `cd frontend && npm install && npm run dev` (Vite :5173, proxies /api).
- Logins (from `seed_demo`): staff `demo` / `demo12345`; operator superuser
  `operator` / `operator12345`.
- **Verify visually in the browser preview** (preview_* tools): check login, every staff
  tab, and the operator console; test responsive (mobile/tablet/desktop) and interactions.
  Note: a dev server may already occupy :5173.

## Design direction
- Modern SaaS aesthetic (think Linear / Stripe / Vercel dashboards): clean, spacious,
  confident typography, subtle depth, purposeful motion (not gratuitous).
- Build a real **design system** first: color tokens (brand + semantic), type scale, spacing,
  radius, shadow, and a small set of reusable primitives (Button, Card, Input, Select,
  Modal/Drawer, Table, Tabs, Badge/Pill, Toast, Skeleton, EmptyState, Avatar). Refactor pages
  onto these primitives — don't leave ad-hoc Tailwind everywhere.
- A proper **app shell**: persistent sidebar nav (collapsible) + top bar (clinic name/switcher
  for operator context, user menu, sign out) instead of the current flat tab strip.
- Motion: page/route transitions, list/stagger reveals, hover/press states, animated
  numbers on stat cards, toast notifications, loading skeletons.
- Consistent states everywhere: loading (skeletons), empty (illustrated), error (friendly),
  success (toasts). Confirm destructive actions.

## Tech choices (you may add frontend deps; keep it lean)
- Recommended: `react-router-dom` (real routes/URLs instead of tab state),
  `framer-motion` (animations), an icon set (`lucide-react`), a headless a11y primitive lib
  (`@headlessui/react` or `radix-ui`) for menus/modals/dropdowns, and a charting lib
  (`recharts`) to replace hand-rolled bars in Analytics. A toast lib (`sonner`) is fine.
- Keep bundle reasonable; prefer Tailwind for styling + the theme config for tokens.
- Confirm these additions with me at the start if you want, but these are sensible defaults.

## Hard constraints (do not break)
- **Backend is off-limits** except reading it. No API/endpoint/model changes; the 262 backend
  tests must stay green (don't touch them). If you think you need a backend change, ask first.
- Preserve **all existing functionality and data flows** — every current action must still work
  (booking lifecycle, recall preview/run with cost confirm, escalation resolve, dev chat's
  "one live Anthropic call per send, no polling", operator CRUD, suspension behavior).
- Keep the **auth/CSRF/session** model and the `api.js` contract. Keep superuser → operator
  console routing and staff → dashboard routing (`me.is_superuser`).
- Keep it **deployable**: `npm run build` must succeed; keep it a static SPA behind the same
  Vite proxy / same-origin API.
- Work on a **feature branch**, commit in reviewable chunks, keep `main` green.

## Suggested build order
1. Design system + Tailwind theme tokens + base primitives + fonts.
2. App shell (sidebar + topbar + routing) and the login page.
3. Refactor staff pages onto the system (Calendar, Analytics, Patients, Escalations, Recalls,
   Settings, Chat) — parity first, then polish + motion.
4. Refactor the operator console to match.
5. Responsive + a11y + dark mode pass; final motion polish; verify everything in preview.

## Open questions to confirm with me at the start
- Brand direction: any color/logo/name preferences, or should you propose a palette?
- Dark mode: required, or nice-to-have?
- Router: OK to introduce `react-router-dom` (URLs per page) — I recommend yes.
- Any pages/features to add or drop during the revamp, or strict parity with today?

Start by confirming the open questions, then propose a short design-system plan before
building.
