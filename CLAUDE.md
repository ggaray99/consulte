# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project identity

Product is **consulte.** (lowercase + trailing dot, Deep Slate). Domain: `consulte.app`. SaaS horizontal for independent professionals (salud, legal, contable, coaching, creativos, bienestar) — public landing + online booking.

`consulte/` = Django config module (settings, urls, wsgi). `core/` = the application (models, views, templates, management commands).

## Common commands

PowerShell (Windows is the dev environment):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

- Run a single test: `python manage.py test core.tests.ClassName.test_method` (note: `core/tests.py` is currently empty — there is no test suite yet).
- Make migrations after model changes: `python manage.py makemigrations core && python manage.py migrate`.
- Seed demo professional: `python manage.py seed_demo_professional [--reset-children]`.
- Link a Django `User` to an existing `Professional` (by email): `python manage.py link_demo_user <username> --email <pro_email> [--superuser]`.
- Mercado Pago setup (run once after setting `MP_ACCESS_TOKEN`):
  - `python manage.py mp_create_plan` — creates the preapproval plan, prints `plan_id` to paste into `MP_PREAPPROVAL_PLAN_ID`.
  - `python manage.py mp_diagnose` — verifies token + plan + back_url are aligned (catches the common TEST/PROD mismatch).
  - `python manage.py mp_create_test_user` — provisions a TEST buyer tied to the current TEST app.

No lint/format tooling is configured. No frontend build — Tailwind is loaded via CDN in templates.

## Architecture (the big picture)

### Two organizational shapes for a professional

`Professional.role` is one of `solo` / `owner` / `member`. A `Professional` is either independent or belongs to an `Organization` (clinic/consultora):

- **Solo**: no `organization`. Lives at `/p/<slug>/` (public_landing).
- **Clinic owner/member**: linked to `Organization`. Owner manages members via `/dashboard/clinic/` and invites via `OrganizationInvitation` (magic-link tokens emailed by Resend). Clinic public page is `/c/<slug>/`.

Critical invariant: **pacientes and turnos are NEVER shared across professionals in the same clinic** — each `Patient` and `Appointment` belongs to a single `Professional`.

### Landing = Professional + 4 repeater models

The public landing for a professional is composed of `Professional` plus four ordered child models, all with toggleable visibility flags on `Professional` (`show_stats`, `show_credentials`, `show_services`, `show_testimonials`, `show_mission`, `show_contact`, `show_map`):

- `LandingStat` — number + label.
- `LandingCredential` — Material Symbol icon + title + subtitle.
- `LandingService` — icon + title + description + optional `price` + `is_bookable` (drives which services appear in the booking flow).
- `LandingTestimonial` — quote + author + rating, optionally tied to an `Appointment` (1 review per turn). Reviews submitted via public link start `is_approved=False`.

### Vertical tints are opt-in

`Professional.vertical` (salud/legal/contable/coaching/creativos/bienestar) maps to a tint color in `VERTICAL_TINTS`. The `accent_color` property gives the tint priority **only when** `theme_primary` is still the default cobalt `#0047ab`. Tints render exclusively on `/p/<slug>` (and clinic equivalent). The rest of the product (dashboard, emails, OG default, favicon) is always cobalt. See `brand/README.md` for the full visual system.

### Appointments

- `Appointment.mode` is `presencial` or `online`. When `online`, `save()` auto-fills `meeting_url` with a deterministic Jitsi room derived from the appointment UUID (`Appointment.generate_meeting_url`) — same UUID always resolves to the same room, so patient and pro join without coordinating.
- `unique_together = ['professional', 'appointment_date', 'appointment_time']` — slot collisions are DB-enforced.
- `price_at_booking` is captured at reservation time so later edits to `LandingService.price` don't rewrite history.
- `service` is optional; null means "consulta general".

### Subscriptions and the operator panel

- `Subscription` (one-to-one with `User`) is auto-created as `free` by `core/signals.py` on user creation. `is_pro` = `plan='pro' AND status in (active|trialing)`. Hard feature-gating by plan is not yet wired up — only the data model and admin flip exist.
- `/operador/` is a parallel admin (superuser-only, gated by `_superuser_required` in `core/views.py`) with KPIs, professional/clinic/appointment browsers, and a manual Pro toggle. `Subscription.manually_set=True` blocks MP webhooks from overwriting an operator override.
- Django's stock `/admin/` is also enabled.

### Mercado Pago billing (Consulte → Pro)

Flow: user clicks "Suscribirme" on `/pricing/` → `billing_subscribe` view → redirect to MP `init_point` of the preapproval plan → user pays → MP redirects to `/billing/return/` and posts events to `/billing/webhook/mp/`.

- `core/billing.py` is a thin requests-based wrapper around MP's REST API. The pattern: if `MP_ACCESS_TOKEN` is empty, `_headers()` raises `BillingNotConfigured` and views render a friendly message — this keeps dev/CI green without MP creds.
- `MP_PREAPPROVAL_PLAN_ID` must be set after running `mp_create_plan` once per environment. TEST and PROD have separate plans; mixing them is the most common failure mode (`mp_diagnose` detects it).
- The cobro Pro→Paciente (marketplace flow where patients pay the pro) is **not implemented** — see memory `next_session_priorities.md`.

### Transactional email (Resend)

`core/emails.py` exposes `send_appointment_confirmation` and `send_clinic_invitation`. Same no-op-if-unconfigured pattern as billing: if `RESEND_API_KEY` is empty, the function logs and returns `False` — booking never fails because of email. Every send is wrapped in try/except. Templates are self-contained HTML+TXT in `templates/core/emails/`.

### OG images

`core/og.py` renders 1200×630 PNGs server-side with Pillow + bundled Manrope/JetBrains Mono variable fonts in `core/static/fonts/`. Two endpoints: `/og/default.png` (marketing) and `/og/p/<slug>.png` (per-professional, uses vertical tint). No headless browser.

### Authenticated layout convention

Every page under `/dashboard/*` includes the shared navbar via `{% include 'core/_app_nav.html' with active='<tab>' %}`. Page-specific actions go in the body, never in the global navbar. See memory `authenticated_pages_navbar.md`.

## Conventions to respect

- **Language**: All user-facing copy is Spanish (`LANGUAGE_CODE = 'es-ar'`, `TIME_ZONE = 'America/Argentina/Buenos_Aires'`). Verbose names on models are in Spanish.
- **Money formatting**: `LandingService.formatted_price` follows Argentine convention for ARS (`$ 15.000` / `$ 1.500,50`) and anglo for USD (`USD 1,200`). Don't reimplement.
- **Views helper**: Use `get_professional(request)` from `core/views.py` to fetch the logged-in user's `Professional` — returns `None` if not set up (redirect to `/setup/`).
- **No-op-on-missing-env pattern**: Both `billing.py` and `emails.py` degrade gracefully when their API keys are absent. New external integrations should follow the same pattern so the dev server stays runnable without secrets.
- **Brand authority**: `brand/README.md` is the canonical design system (cobalt `#0047AB`, Manrope + JetBrains Mono, no dramatic shadows, lowercase wordmark with separate `.dot` span). The `DESIGN paleta de colores.md` at the repo root is a subset reference.

## Deploy

Railway, driven by `Procfile` (release runs migrate + collectstatic; web runs migrate + gunicorn). Postgres via `DATABASE_URL` (`dj_database_url`). Static files served by WhiteNoise. Media uploads need a mounted Volume at `MEDIA_ROOT` for persistence. Production env vars required: `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `MEDIA_ROOT`, plus `RESEND_API_KEY` / `MP_*` if those integrations are active. `SITE_BASE_URL` is used as the fallback for absolute URLs when no request is available (emails, MP back_urls from management commands).
