# Branding config — one product name, one domain, no Neuradigi

This repository is the **AIXO copy** of the CRM, a fully separate copy that takes no further merges from
Neuradigi's own CRM repo (decided 2026-11-16). It still carries Neuradigi's name, domains, logo and a
Neuradigi deploy target, plus several hardcoded stand-in product names ("Core CRM", "Powered by CRM",
"FurnitureCRM"). This track removes every Neuradigi reference and makes the product name and domain
**config values that every surface reads**. A future copy for another client is rebranded by editing the
lines and files listed in the **Rebranding a copy** checklist (Step 9) instead of searching the codebase,
and a CI guard (Step 10) fails the build if a legacy name creeps back.

## Today (audited 2026-11-16)

| Where | What leaks |
|---|---|
| Angular `core/constants/brands.ts` | Hostname-resolved multi-brand table; **Neuradigi CRM is the default brand** and the fallback for every unknown host. AIXO is a second entry. |
| `APP/public/` | Default `favicon.ico`, `icons/*.png`, `images/Logo.svg` and `manifest.webmanifest` ("Neuradigi CRM") are Neuradigi's. AIXO's live under `public/brands/aixo/`. `index.html` title is "Neuradigi CRM". |
| `API/static/images/Logo.svg` | The logo in **every auth email** is Neuradigi's (and SVG, which Gmail/Outlook do not render). |
| `API/config.env` | `EMAIL_SENDER=contact@neuradigi.com`; `APP_NAME=CRM`. |
| Backend copy | Billing emails hardcode `"CRM"` and `support@yourcrm.com`; the trial-ended message exists twice (`subscriptions/exceptions.py` "…the CRM", `subscriptions/middleware.py` "…FurnitureCRM"); sender verification email subject "Verify your CRM sender identity"; Stripe products created as "FurnitureCRM — {plan}"; API root says "FurnitureCRM API is running". |
| Frontend copy | Footer "© Core CRM" with `support@`/`privacy@core-crm.com`; data-deletion page `privacy@core-crm.com`; public store/listings "Powered by Core CRM"; public shell "Powered by CRM"; pricing wordmark "CRM"; AI-assistant preview + settings labels "Powered by CRM"; WhatsApp templates page "without leaving Core CRM"; welcome page "FurnitureCRM is being built…"; verify-token placeholder `furniturecrm-verify-xyz123`. |
| Base template name | Onboarding catalog tile and `packs/base/pack.yaml` call the non-industry template "Core CRM"; sidebar workspace label shows "CRM"; billing compare table's feature category is "Core CRM". |
| Embed widget | Form + AI chat footers hardcode "Powered by CRM"; `loader.ts` hardcodes `https://crm-api.aixoapp.com`; built into the committed `widget/dist/v1/widget.js`. |
| Deploy | `prod-neuradigi` target: `environment.neuradigi.ts`, `angular.json` configuration, `docker-compose.prod-neuradigi.yml`, `run.cmd` / `run.sh` env option, `.sops.yaml` rule. `main.ts` hardcodes both API hosts in Sentry `tracePropagationTargets`. |
| Domain duplication | Google ×3 and Meta OAuth redirect URIs repeat the API host in `config.prod.env` and `config.local.env`; `email.py` reads its own `os.getenv` with a hardcoded `crm.aixoapp.com` default; `environment*.ts` repeats the API origin in `embedWidgetHost`. |
| Samples / seeds / tests | WhatsApp template sample values ("Neuradigi", `neuradigi.com` URLs) in two modules; `seed_admin.py` seeds `devadmin@neuradigi.com`; tests use `reply.neuradigi.com` / "Neuradigi"; docstrings; `test-whatsapp-live.ps1`. |
| Docs | Runbooks and step files under `tasks/` and `docs/` (one file named `step-9-prod-neuradigi-cutover.md`). |

## Target shape

**Sources of truth**

| Value | Lives in | Read by |
|---|---|---|
| `APP_NAME` (`AIXO CRM`) | `API/config.env` — new `# Branding & identity` block at the top | Email `From` display name, auth email templates, billing copy, trial-ended message, sender-verification subject, Stripe product name, TOTP issuer, FastAPI title, API root message, `/app-config` → Angular, public widget/assistant config → embed widget |
| `SUPPORT_EMAIL` (`support@aixoapp.com`), `PRIVACY_EMAIL` (`privacy@aixoapp.com`) | same block | Billing copy, `/app-config` → footer + data-deletion page |
| `EMAIL_SENDER` (`contact@aixoapp.com`) | same block | SMTP `From` address |
| `EMAIL_MESSAGE_ID_DOMAIN`, `LIST_UNSUBSCRIBE_MAILTO` | same block, marked **set once at first deploy** (values unchanged) | Outbound email headers, via `config.py` |
| `FRONTEND_URL`, `API_BASE_URL` | `API/config.<env>.env` | Everything URL-shaped on the backend. The **Google, Gmail, Google Calendar and Meta OAuth redirect URIs default to `f"{API_BASE_URL}/api/v1/<route>"`**; an explicit env value still wins. Webhook URLs (`MICROSOFT_GRAPH_WEBHOOK_URL`, `MAILGUN_WEBHOOK_URL`) stay explicit — empty means "feature off". `MICROSOFT_GRAPH_REDIRECT_URI` stays explicit (see D14). |
| Email logo | `LOGO_URL` defaults to `f"{FRONTEND_URL}/images/logo.png"` | Auth email templates |
| API URL for the browser | `APP/src/environments/environment*.ts` `apiBaseUrl` | The browser needs it before any API call, so it is the frontend's one domain value. `embedWidgetHost` and Sentry trace targets derive from it via `deriveApiOrigin()`. CI pins its origin to `config.prod.env` `API_BASE_URL`. |
| Brand assets | `APP/public/favicon.ico`, `APP/public/icons/*.png`, `APP/public/images/logo.png`, `APP/public/images/Logo.svg` (admin-panel wrapper, D11), `APP/public/manifest.webmanifest`, `APP/src/index.html` title | Browser before boot, accounts layout, admin layout, emails |

**Angular brand flow.** `/app-config` gains `app_name`, `support_email`, `privacy_email`. `BrandService`
becomes a computed view over `AppConfigApiService.config()`: `name` falls back to the static `index.html`
title captured at construction (before any route sets a page title), `logoUrl` is the fixed
`images/logo.png`, and `supportEmail` / `privacyEmail` are `null` when the config is unavailable (links
hidden). Components read brand fields only through `BrandService`. `brands.ts`, `resolveBrand()`,
`legalName` and `public/brands/` are deleted.

**Embed widget.** The public form config (`WidgetConfigPublic`) and the public assistant bootstrap response
gain `platform_name` (= `APP_NAME`). The widget renders `Powered by {platform_name}` and derives its default
API host from its own `<script src>` origin, so the bundle carries no brand and no domain.

**Static copies of the name are pinned, not generated.** `index.html <title>` and the manifest's `name` /
`short_name` are fetched before Angular boots, so they are static. The CI guard asserts they equal
`APP_NAME`. (A prebuild generator was rejected: `ng serve` and direct `ng build` skip npm `prebuild`.)

**CI guard.** `.github/scripts/check_branding.py`, run as its own job in `.github/workflows/quality.yml`
(the workflow runs no pytest, so a pytest guard would never execute). It lists files with `git ls-files`
and fails when: a banned term appears outside its per-line allowlist; any tracked file's blob hash matches
a pre-track Neuradigi image; the title/manifest differ from `APP_NAME`; `APP_NAME` is set in a
`config.<env>.env`; the `environment.ts` API origin differs from `config.prod.env` `API_BASE_URL`; or it
scanned fewer than 500 files (vacuous-pass guard).

## Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **One brand per copy, configured per deployment.** The hostname multi-brand resolver is removed. | User direction 2026-11-16: future clients get *separate copies*. Reverses the 2026-09-13 "one build, many brands" design recorded in `brands.ts`, which assumed one repo serving several brands. |
| D2 | **Runtime name via `/app-config`.** | Already awaited in the app initializer (`app.config.ts`); one source reaches the UI with no build tooling. |
| D3 | **Not per-org white-labelling.** | Orgs already show their own name/logo (header `org()?.name`, `OrgSettings.store_name/logo_url`, widget `branding`). This track is the *platform* name, a deployment property. Benchmarks (product knowledge, **unsourced**): HubSpot/Zoho/Pipedrive hard-code their platform name and offer account-level brand kits — our tenant equivalent already exists; the per-deployment platform name is a deliberate difference because this product is resold as separate deployments. |
| D4 | **Sender `contact@aixoapp.com`** (user decision). | Recipients must not see a Neuradigi address. **Deploy prerequisite:** `aixoapp.com` verified (SPF + DKIM, DMARC recommended) in the Brevo account that `EMAIL_USER` belongs to. |
| D5 | **`prod-neuradigi` deploy target removed** (user decision). | This copy deploys only to `aixoapp.com`. No `secrets.prod-neuradigi.enc.env` exists in this repo. |
| D6 | **`@neuradigi/debug-console` stays** (user decision). | Dev-only overlay, OFF in production. Allowlisted per line (D15). |
| D7 | **Docs scrubbed; GitHub handles kept** (user decision). | `.github/CODEOWNERS` and the ruleset URL in `BRANCH_PROTECTION.md` must name the real GitHub accounts (`github.com/neuradigi/axioapp-crm`). |
| D8 | **Internal identifiers are not renamed** — `X-FurniCRM-Key` header, `furnicrm` CSS/DOM classes, the `furnicrm-widget` package name, module docstrings, the `[FurnitureCRM]` console prefix. | CLAUDE.md: renaming identifiers is breaking (the embed header is a public contract used by installed widgets). Only **user-visible** copy changes. |
| D9 | **WhatsApp template sample values become neutral placeholders** (`Acme Traders`, `example.com`). | They stand for the *customer's* org in Meta's review preview, not our product. |
| D10 | **One raster logo** at `APP/public/images/logo.png` (AIXO, 914×240). Emails load it from `FRONTEND_URL`; `API/static/images/Logo.svg` is deleted. | One file instead of three; PNG renders in Gmail/Outlook, SVG does not. |
| D11 | **Admin panel logo:** `APP/public/images/Logo.svg` is replaced by an SVG embedding `logo.png` as a data URI. | `features/admin/` is untouched by rule and hardcodes `images/Logo.svg`. |
| D12 | **Mailgun inbound domain (`reply.karmcrm.com`) is out of scope.** | Moving it needs DNS + Mailgun setup by the operator; already a config value; listed in the checklist. |
| D13 | **Database rows are audited, not rewritten.** | Existing rows are operator data. Step 10 ships an audit query that also lists privileged accounts on non-AIXO domains; the operator decides. Seeds change so fresh databases are clean. |
| D14 | **`MICROSOFT_GRAPH_REDIRECT_URI` stays explicit and unchanged.** | Config sends `/api/v1/integrations/microsoft/callback` but the API serves `/api/v1/email/microsoft/callback` (pre-existing mismatch, found during review). Deriving it would change a URI registered in Azure. Reported to the user for a separate fix. |
| D15 | **Base template renamed "General"** (user decision) — catalog tile, `packs/base/pack.yaml` `display_name`, sidebar workspace label, billing compare-table category. | "Core CRM" read as a second product name next to the brand. `template_id` stays `base`. |
| D16 | **Single trial-ended message table.** `middleware.py` reuses `exceptions.py`'s messages. | Reuse before create; one place for the copy. |

### Guard: banned terms and per-line allowlist

Banned (case-insensitive): `neuradigi`, `yourcrm`, `core-crm.com`, `Powered by CRM`, `Powered by Core CRM`,
`FurnitureCRM is being built`. Each allowlist entry is **file + a regex the whole line must match** — a file
is never exempt wholesale:

| File | Allowed line |
|---|---|
| `APP/package.json`, `APP/package-lock.json` | lines containing `@neuradigi/debug-console` or `node_modules/@neuradigi/` |
| `APP/src/main.ts` | `import { initDebugConsole } from '@neuradigi/debug-console';` |
| `APP/src/environments/environment*.ts` | the `(@neuradigi/debug-console)` comment line |
| `.github/CODEOWNERS` | lines with `@Neuradigi02` |
| `BRANCH_PROTECTION.md` | the `github.com/Neuradigi02/` ruleset URL line |
| `tasks/branding-config/**` | any line (this track must name what it removes) |
| `.github/scripts/check_branding.py` | any line (it holds the banned list) |

## Cases

- **Existing 2FA enrolments.** The TOTP issuer label changes from "CRM" to "AIXO CRM" for new enrolments only; codes are unaffected (issuer is not part of the secret). `pyotp` percent-encodes the issuer, so the space is safe.
- **`From` header with a space in the name.** Built with `email.utils.formataddr`, which quotes correctly.
- **Reply threading.** `EMAIL_MESSAGE_ID_DOMAIN` keeps its value; already-sent mail keeps threading. The checklist marks it "set once".
- **Sender switch before Brevo verification.** Auth mail (reset, OTP) fails or lands in spam. Hard deploy prerequisite in the Step 2 report and the checklist.
- **Existing Stripe products and invoices.** `seed_stripe_catalog` matches by `metadata.plan_code` and never renames; existing "FurnitureCRM — {plan}" products keep that name until renamed in the Stripe dashboard (test + live), and finalized invoices keep it forever. The Stripe account's business name and statement descriptor are dashboard settings. All listed as manual steps.
- **Installed PWAs.** Android/desktop Chrome pick up the new name/icons on a manifest re-check; iOS home-screen entries keep the old icon/name until re-added. `id`, `start_url` and `scope` are unchanged, so installs stay the same app.
- **Stale SPA tabs** still referencing `brands/aixo/*` after it is deleted show a broken logo until the service worker serves the new build (next navigation/reload).
- **`/app-config` fails.** Name falls back to the `index.html` title (pinned to `APP_NAME`); support/privacy links are hidden.
- **Old emails in inboxes** reference `{API_BASE_URL}/static/images/Logo.svg`; after deletion they show alt text. Accepted — the image was Neuradigi's.
- **Microsoft Graph webhook unset** stays "push off", unchanged (webhook URLs are not derived).
- **Explicit redirect URI set in an env file** still wins over the derived default.
- **Installed embed snippets** keep working: they load `/widget/v1/widget.js` from the API host; the rebuilt bundle derives the same host from its own `src`. The `X-FurniCRM-Key` contract is unchanged.
- **Older API without `platform_name`** (rolling deploy, widget served first): the widget falls back to omitting the name (`Powered by` link hidden) rather than printing a stale one.
- **WhatsApp templates already approved by Meta** keep whatever sample values were submitted; samples only matter at review time. Any stored copies surface in the DB audit.
- **Fresh database.** `seed_admin.py` seeds `devadmin@example.com`; it matches on `admin_user_id`, so re-running against an existing DB never creates a duplicate admin.
- **Database holding Neuradigi values** (prod moved to a new DB in 2026-11): Step 10's audit query.
- **Next copy cloned from this one.** It edits the checklist items, adds `aixo` to the guard's banned list, and the guard then lists every remaining AIXO reference.

## Steps

| Step | Title | Files (approx.) |
|---|---|---|
| 1 | Brand assets: AIXO favicon/icons/logo/manifest at the default paths, admin `Logo.svg` wrapper, `index.html` title | binary assets, `manifest.webmanifest`, `index.html` |
| 2 | Backend: branding block, `/app-config` fields, name + contacts in emails and messages | `config.env`, `config.py`, `app_config_service.py`, `app_utils.py`, `subscriptions/email_templates.py`, `subscriptions/exceptions.py`, `subscriptions/middleware.py`, `email_senders/service.py`, `static/images/Logo.svg` (deleted), test |
| 3 | Backend: OAuth redirect URIs derive from `API_BASE_URL`; remaining backend strings | `config.py`, `config.prod.env`, `config.local.env`, `conversations/adapters/email.py`, `scripts/seed_stripe_catalog.py`, `app/main.py`, test |
| 4 | Frontend: single brand from `/app-config` | `brands.ts` (deleted), `brand.service.ts`, `schemas/common.ts`, `footer.component.*`, `data-deletion-status.component.*`, `welcome.component.html`, `main.ts`, `environment*.ts`, `public/brands/` (deleted) |
| 5 | Frontend product-name copy + base template "General" | `public-shell.component.ts`, `store.component.html`, `listings.component.html`, `pricing.page.html`, `whatsapp-templates.page.html`, `whatsapp-card.component.html`, `assistant-preview` + `assistant-interface-tab` + `embed-integrations-tab` labels, `sidebar.component.ts`, `plan-compare-table.component.ts`, `catalog_config.py`, `packs/base/pack.yaml`, `test_packs_catalog.py` |
| 6 | Embed widget: `platform_name` in public configs; widget renders it and derives its host | `embed/schemas.py`, `embed/service.py`, ai-assistants public schema + service, `widget/src/{types,renderer,chat,loader}.ts`, `widget/dist/v1/widget.js`, tests |
| 7 | Remove `prod-neuradigi` deploy target | `environment.neuradigi.ts` (deleted), `angular.json`, `docker-compose.prod-neuradigi.yml` (deleted), `run.cmd`, `run.sh`, `.sops.yaml`, env-file comments |
| 8 | Neutralise samples, seeds, scripts, tests, docstrings | `whatsapp/meta_variables.py`, `whatsapp/templates_service.py`, `seeds/seed_admin.py`, `shared/email/org_sender.py`, `scripts/mailgun_route_setup.py`, `embed-snippet-modal.component.ts`, 4 test files, `test-whatsapp-live.ps1` |
| 9 | Docs scrub + "Rebranding a copy" checklist | `tasks/**`, `docs/**`, `README.md`, `CLAUDE.md` pointer, `tasks/README.md` |
| 10 | CI guard + DB audit query | `.github/scripts/check_branding.py`, `.github/workflows/quality.yml`, `tasks/branding-config/db-audit.sql` |

Order check: Step 1 makes every brand path AIXO **before** Step 4 removes the hostname resolver, so no
deploy between steps shows Neuradigi. Step 2's `LOGO_URL` points at Step 1's `images/logo.png`. Step 4
needs Step 2's `/app-config` fields. Step 6 needs Step 2's `APP_NAME`. The guard (Step 10) lands last
because it can only pass once Steps 1–9 have removed every reference.

## Tests

- **Step 1** — Every path referenced by `index.html`, `manifest.webmanifest`, `ngsw-config.json` and `brands.ts` exists; no file under `APP/public/` has a pre-track Neuradigi blob hash; `ng build` succeeds; login page, favicon and admin layout show the AIXO logo (visual).
- **Step 2** — `GET /app-config` returns exactly the previous keys plus `app_name`, `support_email`, `privacy_email`, equal to config. Every billing email subject/body contains `APP_NAME` and `SUPPORT_EMAIL` and none contains `yourcrm` or `FurnitureCRM`. Middleware and `exceptions.py` return the same trial-ended text, containing `APP_NAME`. Sender-verification subject contains `APP_NAME`. `From` header round-trips through `email.utils.parseaddr` to (`APP_NAME`, `EMAIL_SENDER`). `LOGO_URL` default is `f"{FRONTEND_URL}/images/logo.png"`.
- **Step 3** — With the four redirect env vars unset, each equals `f"{API_BASE_URL}/api/v1/<route>"` and that route exists on the app (asserted against `app.routes`); with one set explicitly, the explicit value wins; derived values equal the literals removed from `config.prod.env` / `config.local.env` (checked before deletion). `email.py` reads both header values from `config`.
- **Step 4** — `ng build` (production + development), `tsc --noEmit`, eslint clean. `BrandService.name()` equals the captured `index.html` title before `/app-config` resolves and `app_name` after; footer hides support/privacy links when null. Built bundle contains no `neuradigi` except `3rdpartylicenses.txt`.
- **Step 5** — `test_packs_catalog` asserts the base tile is "General"; `ng build` clean; grep of `APP/src` for `Powered by CRM` / `Core CRM` in templates returns nothing.
- **Step 6** — Public form config and assistant bootstrap responses include `platform_name == APP_NAME`; widget vitest: footer reads `Powered by <platform_name>`, omitted when absent; loader default host equals the script's origin; `widget.js` rebuilt and under its size budget.
- **Step 7** — `run env prod-neuradigi` is rejected with the local/prod usage message (cmd + sh); `angular.json` has no `production-neuradigi`; `ng build` still succeeds.
- **Step 8** — WhatsApp sample, Mailgun step-2/step-4/byte-identical and auto-reply tests pass with neutral values.
- **Step 9** — Checklist lists every source-of-truth line/file in this README plus the per-copy third-party identities and secrets.
- **Step 10** — Guard passes on the branch; seeded violations (a banned word in a new file, a pre-track image hash, a title mismatch, `APP_NAME` in `config.prod.env`) each fail it; the CI job runs on PRs to `dev`/`main`.
