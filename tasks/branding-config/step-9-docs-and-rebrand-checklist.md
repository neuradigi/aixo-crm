# Step 9 — Docs scrub + "Rebranding a copy" checklist

**Goal:** docs carry no Neuradigi references (GitHub handles excepted, D7), and one checklist lists
everything a new copy edits.

## Files

- `tasks/**/*.md`, `docs/**/*.md` — Neuradigi domains and names → AIXO values or `example.com` placeholders.
- `tasks/r2-storage/step-9-prod-neuradigi-cutover.md` → `step-9-prod-cutover.md`, plus links to it.
- `README.md` — new **Rebranding a copy** section:
  1. `API/config.env` Branding & identity block (name, contacts, sender; Message-ID domain set once).
  2. `API/config.<env>.env` `FRONTEND_URL` / `API_BASE_URL`, plus `MICROSOFT_GRAPH_REDIRECT_URI`, webhook URLs, Mailgun domains.
  3. `APP/src/environments/environment*.ts` `apiBaseUrl`, Sentry DSN / environment.
  4. Brand assets: `favicon.ico`, `icons/*`, `images/logo.png`, `images/Logo.svg`, manifest name, `index.html` title.
  5. `nginx/<domain>.conf`.
  6. Per-copy third-party identities and secrets: Brevo sender domain (+ DMARC), Stripe account (business
     name, statement descriptor, products), Google / Microsoft / Meta app names and redirect URIs, Mailgun
     domain + routes, reCAPTCHA domains, Firebase project, Sentry projects, `.sops.yaml` recipients, and
     regenerated JWT / Fernet / encryption keys.
  7. Add the previous brand to the guard's banned list.
- `CLAUDE.md` — one-line pointer to the checklist; `tasks/README.md` — list this track.

## Tests

- The checklist covers every row of the README's source-of-truth table.
- `git grep -i neuradigi -- tasks docs` returns only `tasks/branding-config/**`.
