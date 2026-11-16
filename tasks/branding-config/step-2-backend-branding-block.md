# Step 2 — Backend branding block, `/app-config` fields, name + contacts in emails and messages

**Goal:** `API/config.env` holds one `# Branding & identity` block, and every backend message and email
reads the product name and contact addresses from it.

## Files

- `API/config.env` — new block at the top: `APP_NAME=AIXO CRM`, `SUPPORT_EMAIL=support@aixoapp.com`,
  `PRIVACY_EMAIL=privacy@aixoapp.com`, `EMAIL_SENDER=contact@aixoapp.com` (moved from the SMTP block),
  `EMAIL_MESSAGE_ID_DOMAIN` + `LIST_UNSUBSCRIBE_MAILTO` (moved, values unchanged, marked "set once").
- `API/config.py` — expose `SUPPORT_EMAIL`, `PRIVACY_EMAIL`, `EMAIL_MESSAGE_ID_DOMAIN`,
  `LIST_UNSUBSCRIBE_MAILTO`; `LOGO_URL` default → `f"{FRONTEND_URL}/images/logo.png"`.
- `API/src/services/app_config_service.py` — add `app_name`, `support_email`, `privacy_email`.
- `API/src/utilities/app_utils.py` — `From` via `email.utils.formataddr((APP_NAME, EMAIL_SENDER))`.
- `API/src/app/core/subscriptions/email_templates.py` — drop the `_PRODUCT_NAME` / `_SUPPORT_EMAIL`
  constants; read `APP_NAME` / `SUPPORT_EMAIL` from `config`.
- `API/src/app/core/subscriptions/exceptions.py` — trial-ended / read-only copy uses `APP_NAME`.
- `API/src/app/core/subscriptions/middleware.py` — reuses `exceptions.py`'s message table (D16).
- `API/src/app/core/email_senders/service.py` — both verification subjects use `APP_NAME`.
- `API/static/images/Logo.svg` — deleted (D10).
- Test: `API/tests/test_branding_config.py`.

## Tests

- `/app-config` keys = previous keys + `app_name`, `support_email`, `privacy_email`; values equal config.
- Every billing template: subject/body contain `APP_NAME` and `SUPPORT_EMAIL`; none contains `yourcrm` or `FurnitureCRM`.
- Middleware and `exceptions.py` trial-ended text are identical and contain `APP_NAME`.
- `parseaddr` of the built `From` header == (`APP_NAME`, `EMAIL_SENDER`).

## Deploy prerequisite (state in the report)

`aixoapp.com` verified in Brevo (SPF + DKIM; DMARC recommended); `support@` and `privacy@aixoapp.com` exist.
