# Step 3 — OAuth redirect URIs derive from `API_BASE_URL`; remaining backend strings

**Goal:** the API host is written once per environment; no backend code holds a brand or domain literal.

## Files

- `API/config.py` — `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_GMAIL_REDIRECT_URI`, `GOOGLE_CALENDAR_REDIRECT_URI`,
  `META_OAUTH_REDIRECT_URI` default to `f"{API_BASE_URL}/api/v1/<route>"`. `MICROSOFT_GRAPH_REDIRECT_URI`
  and every webhook URL untouched (D14; empty = feature off).
- `API/config.prod.env`, `API/config.local.env` — delete those four redirect lines, after asserting the
  derived values equal them.
- `API/src/app/core/conversations/adapters/email.py` — import `EMAIL_MESSAGE_ID_DOMAIN` /
  `LIST_UNSUBSCRIBE_MAILTO` from `config` (no own `os.getenv`, no host default).
- `API/src/app/scripts/seed_stripe_catalog.py` — product name `f"{APP_NAME} — {plan.name}"`.
- `API/src/app/main.py` — startup/shutdown log lines and root message use `APP_NAME`.
- Test: extend `API/tests/test_branding_config.py`.

## Tests

- Env vars unset → each derived URI == `f"{API_BASE_URL}/api/v1/<route>"`, and that route exists in `app.routes`.
- An explicit env value wins.
- Root endpoint message contains `APP_NAME`.

## Report

Existing Stripe products keep their name — rename them in the Stripe dashboard (test + live) and set the
account business name / statement descriptor. Microsoft redirect mismatch (D14) reported separately.
