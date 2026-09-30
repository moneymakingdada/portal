# Portal — phone verification and customer messaging for Ghana

Two things in one platform:
1. **OTP API** — send and check one-time SMS codes for Ghanaian phone numbers (an Arkesel-style verification API).
2. **Customer messaging** — send a thank-you note after a sale, a birthday wish, a holiday greeting, or your
   own message to your customers, with suggested templates for each occasion and optional fully-automatic
   birthday sends.

Plus a React dashboard: sign-up (SMS-verified), login, API keys, a customer list, message templates, message
history and a prepaid wallet.

```
portal/
├── backend/    Django 6 + DRF + Celery + Redis + PostgreSQL
└── frontend/   React 19 + Vite, plain CSS (no UI framework)
```

## Quick start (local development)

**1. Start Postgres and Redis**

```bash
docker compose up -d
```

**2. Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # defaults already match docker-compose.yml
python manage.py migrate
python manage.py createsuperuser   # optional, for /admin
python manage.py runserver
```

The API is now at `http://127.0.0.1:8000`. With `SMS_BACKEND=console` (the
`.env.example` default), every message — verification codes included — is
printed to this terminal instead of being sent, so you can test the whole
flow without a provider account.

Run the Celery worker in a second terminal if you turn off
`CELERY_TASK_ALWAYS_EAGER` (it's `True` by default in debug, so tasks run
inline and you can usually skip this):

```bash
celery -A config worker -l info
```

Automatic birthday messages need a beat process (skip this if you don't need
them running locally):

```bash
celery -A config beat -l info
```

**3. Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to Django, so cookies and
CSRF work exactly as they will once both are served from behind the same
domain in production — no CORS configuration needed.

## Running the tests

```bash
# Backend (197 tests). Runs on SQLite by default; set DATABASE_URL to also
# check against PostgreSQL (a few concurrency tests only run for real
# against Postgres — SQLite skips them).
cd backend && python manage.py test --settings=config.settings_test

# Frontend (41 tests)
cd frontend && npm test
```

## Going live

Three things gate real SMS sending, and Django's own `check --deploy`
refuses to boot without them once `DJANGO_DEBUG=False`:

1. `DJANGO_SECRET_KEY` and `OTP_HMAC_KEY` — two different long random values
2. `SMS_BACKEND=arkesel` plus `ARKESEL_API_KEY` — `console`/`memory` backends
   are refused outside debug mode
3. `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` set to your real domain(s)

For real wallet top-ups, set `PAYSTACK_SECRET_KEY` and `FRONTEND_URL`, and
give Paystack your webhook URL in their dashboard:
`https://YOUR-DOMAIN/api/webhooks/paystack`. Until then, top-ups fail
gracefully with a "couldn't reach the payment provider" error.

Add credit to an account from the command line — useful for testing, or for
manually honouring a Mobile Money payment made outside Paystack:

```bash
python manage.py add_credit someone@example.com 50   # +GHS 50.00
python manage.py seed_plans                          # starter set of Buy SMS plans (GHS 20-500)
```

## What's implemented

**Verification**
- Sign-up with mandatory SMS verification, session login with lockouts on
  repeated failures, and the OTP API itself (`/api/v1/otp/send`,
  `/otp/verify`) — API-key auth, per-phone/per-IP/per-org rate limits,
  single-use codes stored only as keyed HMAC hashes

**Customer messaging** (`/api/v1/messages/send`)
- Thank-you, birthday, holiday, welcome and custom messages to a phone
  number, with a suggested body for every category so there's nothing to
  write before your first send
- A customer record is created or updated automatically from the phone
  number you send to, unless you opt out with `save_customer: false`
- **Automatic birthday messages**: turn it on once from the dashboard's
  Customers page, and every customer with a birthday on file gets your
  birthday template on the day, via a daily Celery beat task — no API call
  needed. Each send is keyed so a second run on the same day never repeats it
- Save your own template per category (`messaging/templates.py` has the
  built-in suggestions); the dashboard's Templates page edits these directly
- Everything shares one wallet, one daily spend cap, and one message log with
  OTP sends — a `category` field tells them apart

**Wallet top-ups** (`/api/wallet/topup`, `/wallet/topup/verify`, `/api/webhooks/paystack`)
- Pay any custom amount, or buy a listed plan from the dashboard's Buy SMS
  page (`messaging.SmsPlan`, managed in `/admin` — `seed_plans` creates a
  starter set)
- Paystack's hosted checkout takes the payment; card and Mobile Money details
  never touch this server
- Credited exactly once no matter which arrives first (or if both do): the
  webhook Paystack calls the moment a charge succeeds, or the check the
  dashboard runs when the customer's browser returns from checkout. Amount
  and currency are re-verified against what the payment was for before
  anything is credited

**Shared infrastructure**
- **Wallet** — an append-only, idempotent ledger (`messaging/ledger.py`);
  every debit, refund, top-up and adjustment is one row, balances never go
  negative (enforced by both application logic and a DB constraint)
- **Dashboard** — overview stats, customers, templates, API key management,
  the combined message log (filterable by status and category), the wallet
  ledger, and an interactive quickstart with copy-paste code samples for both
  APIs
- **Landing page** — describes every platform component and its status
  (available vs. coming soon)

See `backend/.env.example` and `frontend/.env.example` for every configuration
knob, each with an explanation of what it does.
