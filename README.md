# Expense Tracker

Snap a photo of a receipt and the app reads it, checks it and files it. You confirm each receipt with one tap before anything reaches your ledger.

- **Backend:** FastAPI, SQLAlchemy, Alembic, Postgres (`backend/`)
- **Frontend:** React, Vite, Tailwind, TanStack Query, Framer Motion (`frontend/`)
- **AI:** Claude vision with structured outputs: a fast model for the photo check and categories, a stronger model for extraction

## How a receipt flows

1. **Upload.** The photo is resized, its GPS data is stripped, and it is stored. The API returns immediately and the receipt joins a queue in Postgres; a pool of `READER_WORKERS` (default 4) reads several at once, and anything cut off by a restart is picked up again.
2. **Quality gate.** A fast model checks it is a readable receipt; if not, the inbox asks for a retake with a hint.
3. **Extract.** A strong model reads every field into a JSON schema (validated in code): merchant (address, tax IDs), customer, line items, each tax line, fees, payments, an open `extras` list, and the full text. It detects the country and reads dates and numbers the local way.
4. **Check.** Code verifies that items, taxes and fees add up to the total, that the date is plausible and that tax IDs look valid. If a check fails, extraction is retried once with the problems spelled out.
5. **Enrich.** Duplicates are flagged, the category comes from your past choices or the model, and foreign currency is converted at that day's ECB rate (or a community rate for currencies the ECB doesn't publish).
6. **Confirm.** The receipt waits in the review panel as a prefilled card. Edit anything, then confirm; your edits teach the category rules.

## Run it locally

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+, Postgres 16 (or Docker).

```bash
# 1. Database
docker compose up -d db

# 2. Backend
cd backend
cp .env.example .env          # add your ANTHROPIC_API_KEY
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8001   # the frontend proxies /api here (API_PORT to change)

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5174 (pinned; set WEB_PORT and APP_URL to change it)
```

To try the UI without an API key, load sample data: `cd backend && uv run python -m scripts.seed_demo`, then sign in as `abc@example.com` / `demo-password-123`.

## Security

- **Accounts.** People sign up with name, email and password (scrypt-hashed); every receipt, expense, category and budget belongs to one account and other accounts can't see or use it. The first account takes over data recorded before accounts existed. Set `ALLOW_SIGNUP=false` to close sign-ups. Sessions are HMAC-signed, httpOnly, `SameSite=Strict` cookies; the signing secret is `SESSION_SECRET` or a random one kept in `backend/data/session_secret`.
- **HTTPS.** Behind TLS, set `COOKIE_SECURE=true` and `HSTS=true`.
- **Abuse limits.** Uploads and retries share an hourly budget (`UPLOADS_PER_HOUR`), at most `MAX_FILES_PER_UPLOAD` photos per request, and login attempts are rate limited.
- **Data minimisation.** Full card numbers in extracted text are masked to the last four digits. Discarding a receipt or deleting an expense deletes its photo and extracted text.
- **Uploads.** Files are decoded and re-encoded as JPEG (EXIF stripped), capped at 20 MB and 60 MP to stop decompression bombs.
- **Headers.** CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and `Permissions-Policy` on every response.
- **Claude API.** Receipt photos are sent to the Claude API for extraction; keep `ANTHROPIC_API_KEY` in `.env`, which is git-ignored.

## Tests

```bash
cd backend
createdb expense_test          # once; or set DATABASE_URL to another empty database
uv run pytest
```

The tests use a fake model, so they don't call the Claude API.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/signup` | Create an account (name, email, password) and sign in |
| POST | `/api/auth/login` · `/api/auth/logout` | Sign in or out |
| GET | `/api/auth/me` | Who is signed in, and whether sign-up is open |
| POST | `/api/receipts` | Upload one or more photos (`files`) |
| GET | `/api/receipts?status=open` | Inbox: processing, ready, needs review, retake, failed |
| POST | `/api/receipts/{id}/confirm` | Save the (edited) draft as an expense |
| POST | `/api/receipts/{id}/discard` · `/retry` | Drop or re-run a receipt |
| GET | `/api/expenses?month=YYYY-MM&q=&category_id=` | Search confirmed expenses |
| GET | `/api/expenses/export.csv` | CSV export |
| GET | `/api/summary?month=YYYY-MM` | Totals, categories, budgets and insights |
| GET | `/api/summary/months?year=YYYY` | Spend per month, for the calendar picker |
| GET/PUT | `/api/settings`, `/api/budgets`, `/api/categories` | Preferences. Changing the home currency re-converts expenses and budgets |
| POST | `/api/settings/detect` | Sets the home currency from the browser's time zone and locale until you pick one |

Interactive docs are at http://localhost:8001/docs.

## Deploy to Railway

The root `Dockerfile` builds one image that runs everything: the API, the receipt readers and
the web app, on one address. `railway.json` tells Railway to use it, and the container applies
database migrations each time it starts.

1. In a Railway project, add a **PostgreSQL** database, then an empty service for the app.
2. Deploy the code to the app service: connect the GitHub repo, or run `railway up` from this
   folder with the Railway CLI.
3. On the app service, add a **Volume** mounted at `/data`. Receipt photos live there and
   survive redeploys.
4. Set these variables on the app service:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (a reference to the database) |
   | `ANTHROPIC_API_KEY` | your key |
   | `SESSION_SECRET` | a long random string, e.g. from `openssl rand -base64 32` |
   | `UPLOAD_DIR` | `/data/uploads` |
   | `COOKIE_SECURE` | `true` |
   | `HSTS` | `true` |

5. Under **Networking**, generate a domain, open it and create your account. Once everyone who
   should have an account has one, set `ALLOW_SIGNUP=false`.

### Email: confirming accounts and resetting passwords

Every email sign-up must click a link we email before the account can be used, and the sign-in
page offers **Forgot password?**. Links point at the Railway domain automatically (set `APP_URL`
for a custom domain), never at the address a request claims to come from. Without a way to send
email, signing up with an email address is switched off and only the buttons below are offered.

Set `EMAIL_FROM` plus one provider:

| Provider | Variables | Notes |
| --- | --- | --- |
| [Brevo](https://www.brevo.com) | `BREVO_API_KEY` | Free tier; can send from a single verified address, e.g. a Gmail one, without owning a domain. |
| [Resend](https://resend.com) | `RESEND_API_KEY` | Needs a domain you own to email anyone but yourself. |
| SMTP, e.g. Gmail | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD` | Gmail: `smtp.gmail.com`, port 587, and an [app password](https://myaccount.google.com/apppasswords). Railway blocks SMTP below its Pro plan. |

For local testing, `EMAIL_CONSOLE=true` prints each email, link included, in the backend's log
instead of sending it.

How it's kept safe:
- Links are single use, stored only as hashes, and expire (48 hours to confirm, 60 minutes to
  reset). A newer link voids older ones, and changing the password voids them all.
- Resetting or changing a password signs the account out everywhere else and emails a
  "your password was changed" alert. Changing it in Settings asks for the current one.
- Unknown addresses get the same answer as known ones; sends and sign-in attempts are rate
  limited per address and per account.
- **Keep me signed in** keeps a session for 30 days; otherwise it ends when the browser closes
  (and after 12 hours at most).

### Sign in with Google, Microsoft or Apple

Each button appears once its variables are set. Register this redirect URI with each provider:
`https://<your domain>/api/auth/<google|microsoft|apple>/callback`.

- **Google** ([Cloud Console](https://console.cloud.google.com/apis/credentials)): set up the
  OAuth consent screen (External) and publish it, then create an OAuth client ID of type *Web
  application*. Variables: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
- **Microsoft** (Outlook, Hotmail, Live; [Entra app registrations](https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)):
  new registration for *accounts in any organizational directory and personal Microsoft
  accounts*, with a *Web* redirect URI; then add a client secret (note when it expires).
  Variables: `MICROSOFT_CLIENT_ID` (the Application ID), `MICROSOFT_CLIENT_SECRET` (the secret's
  value). Work and school accounts are only matched by email if you add the optional `xms_edov`
  ID-token claim under *Token configuration*.
- **Apple** (needs the paid [Apple Developer Program](https://developer.apple.com/account)):
  create a Services ID with Sign in with Apple, your domain and the return URL, and a key with
  Sign in with Apple. Variables: `APPLE_CLIENT_ID` (the Services ID), `APPLE_TEAM_ID`,
  `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` (the .p8 file's contents). Apple only works over HTTPS, so
  not on localhost.

Sign-in uses the authorization code flow with a per-browser state, a nonce and (Google,
Microsoft) PKCE; the ID token's signature, issuer, audience and expiry are checked against the
provider's published keys. Only an email the provider vouches for is used to find an existing
account, and doing so removes any password set on it by someone who never confirmed the address.
