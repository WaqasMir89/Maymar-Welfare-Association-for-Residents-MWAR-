---
name: run-mwar
description: Build, run, and screenshot the M.W.A.R Digital Platform (Django RWA app for Maymar Welfare Association). Use when asked to run, start, serve, smoke-test, or screenshot the MWAR app/site, or to verify a change works in the running app.
---

# Run the M.W.A.R Digital Platform

A bilingual (Urdu/English, RTL) Django 5 RWA platform. Primary UI is
server-rendered templates + HTMX; SQLite in dev, Postgres in prod. The agent
path is: start `runserver`, then drive it with **`scripts/shoot.mjs`**
(headless Chromium via `playwright-core`) which logs in across roles,
screenshots every surface, and exits non-zero on any 5xx — so it doubles as a
smoke test.

All paths below are relative to the unit dir (`mwar_platform/`). The driver
lives at `.claude/skills/run-mwar/` only by convention — the actual committed
driver is `scripts/shoot.mjs` (it graduated into the project's `scripts/`).

## Prerequisites

The repo's Python venv lives one level up at `../.venv` (parent of the unit).
Activate it; if missing, create it:

```bash
python3 -m venv ../.venv
source ../.venv/bin/activate
pip install -r requirements.txt
```

Argon2 hashing and CNIC encryption are required at runtime — they're in
`requirements.txt` (`argon2-cffi`, `cryptography`). Python 3.12–3.14 all work
(developed on 3.14, Django 5.2.15).

## Build & seed

```bash
source ../.venv/bin/activate
python manage.py migrate
python manage.py seed_demo
```

`seed_demo` is idempotent-ish (safe to re-run) and prints the demo logins. It
drives the *real* application→approval workflow, so it exercises the service
layer, not just fixtures.

## Run (agent path) — drive + screenshot

Start the server in the background, then run the driver:

```bash
source ../.venv/bin/activate
nohup python manage.py runserver 127.0.0.1:8009 > /tmp/mwar_server.log 2>&1 &
sleep 5
curl -s http://127.0.0.1:8009/healthz        # -> {"status": "ok", "db": true}
node scripts/shoot.mjs                        # screenshots -> scripts/shots/
```

`scripts/shoot.mjs` (uses `playwright-core` against the cached Chromium at
`~/.cache/ms-playwright/chromium-1223/...`; override with `CHROME_BIN`):

- visits home, projects, transparency, apply, login (public);
- logs in as **secretary / finance** and captures the staff dashboard,
  membership queue, billing board, complaints;
- toggles **Urdu** and re-shoots the home page to prove RTL mirroring;
- prints `All pages rendered cleanly.` and exits 0, or lists any `5xx` and
  exits 1.

PNGs land in `scripts/shots/` (`01-home.png` … `10-home-urdu.png`). **Open one
to confirm it's not blank.**

Install the driver's one dependency if `node_modules` is absent:

```bash
npm install playwright-core
```

## Direct invocation (no browser)

Exercise the domain/service layer directly — fastest for PR work that touches
internals:

```bash
source ../.venv/bin/activate
python manage.py test apps.members.tests apps.dues.tests apps.core.tests_api   # 28 tests
```

Or poke a single flow through the Django test client / shell, e.g. confirm PII
access is audited when a Chairman views an application:

```bash
python manage.py shell -c "
from django.test import Client; from apps.accounts.models import User
from apps.core.models import AuditLog; from apps.members.models import MembershipApplication
c = Client(); c.force_login(User.objects.get(email='chairman@mwar.org.pk'))
app = MembershipApplication.objects.exclude(status='draft').first()
before = AuditLog.objects.filter(action='pii_access').count()
c.get(f'/members/staff/applications/{app.id}/')
print('PII logged:', AuditLog.objects.filter(action='pii_access').count() > before)
"
```

## Run (human path)

```bash
python manage.py runserver        # http://127.0.0.1:8000
```

Then sign in at `/accounts/login/` (see demo logins below). Useless headless —
use the driver above to verify without a display.

### Demo logins (from `seed_demo`)

| Role | Email | Password |
|---|---|---|
| Super Admin | `admin@mwar.org.pk` | `admin12345` |
| Chairman (final approval, `view_pii`) | `chairman@mwar.org.pk` | `staff12345` |
| Secretary (review, `view_pii`) | `secretary@mwar.org.pk` | `staff12345` |
| Finance (record payments) | `finance@mwar.org.pk` | `staff12345` |

## Gotchas

- **Switching logged-in user in the driver requires a logout first.** The login
  view redirects authenticated users away from `/accounts/login/`, so the form
  isn't present — `shoot.mjs` hits `/accounts/logout/` before each `login()`.
  Forget this and `page.fill('input[name=email]')` times out.
- **Tickets are mounted at `/complaints/` with URL namespace `complaints`**, not
  `tickets`. Reverse with `{% url 'complaints:list' %}`; `tickets:` raises
  `NoReverseMatch` (500). The app *label* is still `tickets`.
- **`property` is a model field on `MembershipApplication` and `DuesInvoice`**,
  which shadows the `property` builtin inside those class bodies. Computed
  attributes there use `@builtins.property` — don't "fix" them to `@property`
  or the module won't import (`TypeError: 'ForeignKey' object is not callable`).
- **`makemigrations` with no app args printed "No changes detected"** on first
  run (the apps live under `apps/` with custom labels). Pass the labels
  explicitly the first time: `python manage.py makemigrations core accounts
  locality members dues tickets content`.
- **CNIC is ciphertext in the DB.** A raw `SELECT cnic FROM members_memberprofile`
  returns a `gAAAAA…` Fernet token, not digits. Read through the ORM (it
  decrypts) and expect `masked_cnic` (`*****-*****67-*`) in the UI unless the
  user holds `members.view_pii`.
- **Urdu UI direction flips but body text stays English** — only the chrome is
  translated; no compiled `.po` catalog ships yet. RTL layout mirroring is the
  thing to verify in `10-home-urdu.png`, not translated copy.

## Troubleshooting

- `ValueError: Couldn't load 'Argon2PasswordHasher'` → `pip install argon2-cffi`.
- `curl http://127.0.0.1:8009/` returns `000` → server didn't stay up; check
  `/tmp/mwar_server.log` (often a `SyntaxError` from a half-applied edit, or the
  port is taken — `pkill -f "runserver 127.0.0.1:8009"` and restart).
- Driver: `ERR_MODULE_NOT_FOUND: playwright-core` → run from the unit dir (where
  `node_modules` is) or `npm install playwright-core` first.
- Health: `GET /healthz` → `{"status":"ok","db":true}` when the DB is reachable.
