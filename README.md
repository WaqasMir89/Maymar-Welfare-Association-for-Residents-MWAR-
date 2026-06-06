# M.W.A.R Digital Platform

A Resident Welfare Association (RWA) management platform for the **Maymar
Welfare Association for Residents (M.W.A.R)**, Reg. No. 0060 — Gulshan-e-Maymar,
Karachi. Built to the revised v2.0 specification (docs `00`–`08` in the parent
directory).

> The unit of everything is a **household/property** and its **residents**.
> Membership is bound to property and residency (Owner → Permanent Member,
> Tenant → Associate Member), funded by a Rs. 500 registration fee and recurring
> maintenance dues.

## Stack

- **Python 3.12+ / Django 5.2** — server-rendered templates + HTMX + Alpine.js
  (the primary UI). DRF is scaffolded as the secondary API surface.
- **PostgreSQL** in production; **SQLite** out-of-the-box in dev.
- **Bilingual Urdu/English**, full RTL, `Asia/Karachi`, PKR.
- **whitenoise** static serving, **Argon2** password hashing, **Fernet**
  field-level CNIC encryption.

## Apps

| App | Responsibility |
|---|---|
| `core` | Base models, audit log, CNIC crypto, SMS gateway, health check, brand |
| `accounts` | Custom email-login `User`, `StaffProfile`, RBAC groups |
| `locality` | Sector → Sub-Sector → Property registry |
| `members` | Applications, two-step approval, member number, fee receipt, QR ID card |
| `dues` | Dues plans, billing runs, payments, donations, expenses, transparency |
| `tickets` | RWA complaints (water/security/sanitation/…) with threaded messages |
| `content` | Projects, notices/broadcasts, events |

## Quick start (local, SQLite)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # synthetic demo data (synthetic CNICs only)
python manage.py runserver
```

Open http://127.0.0.1:8000. Demo logins (created by `seed_demo`):

| Role | Email | Password |
|---|---|---|
| Super Admin | `admin@mwar.org.pk` | `admin12345` |
| Chairman (final approval, `view_pii`) | `chairman@mwar.org.pk` | `staff12345` |
| Secretary (review, `view_pii`) | `secretary@mwar.org.pk` | `staff12345` |
| Finance (record payments) | `finance@mwar.org.pk` | `staff12345` |

## Key flows to try

1. **Become a Member** (`/members/apply/`) — multi-step wizard, owner/tenant
   branch, declaration, document upload.
2. **Membership queue** (`/members/staff/queue/`) — Secretary reviews → Chairman
   final-approves → member number + Rs 500 receipt + QR ID card all issued
   atomically.
3. **Card verification** (`/members/verify/<token>/`) — public; reveals only
   name/number/status, never PII.
4. **Dues & billing** (`/dues/staff/billing/`) — record a payment (idempotent).
5. **Transparency** (`/transparency/`) — public finance summary.

## Security highlights (per doc 06)

- **CNIC** is Fernet-encrypted at rest (ciphertext in the DB) with a separate
  blind-hash column for uniqueness; **masked** everywhere (`*****-*****67-*`)
  unless the viewer holds `members.view_pii`.
- Every unmasked CNIC read writes a **`PII_ACCESS`** entry to the append-only
  `AuditLog`; approvals and payments are audited too.
- RBAC via Django Groups + Permissions (`python manage.py setup_rbac`).
  `view_pii` is granted explicitly, not bundled by default.

## Tests

```bash
python manage.py test apps.members.tests apps.dues.tests
```

Covers the critical paths: CNIC encrypt/mask, two-step approval (+ idempotency
+ audit), dues billing run and idempotent payments.

## Run / screenshot harness

See `.claude/skills/run-mwar/SKILL.md`. The driver `scripts/shoot.mjs` launches
headless Chromium, logs in across roles, and screenshots every surface (also a
smoke test — it fails on any 5xx).

## Production (Docker Compose)

```bash
cp .env.example .env   # set SECRET_KEY + CNIC_ENCRYPTION_KEY
docker compose up --build -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py setup_rbac
```

Topology (doc 07, Phase 1): nginx → gunicorn/Django → PostgreSQL. No
Redis/Celery/Prometheus until scale justifies them. **Back up `pg_dump`
nightly, encrypted, off-box** — the single VPS is a single point of failure.
