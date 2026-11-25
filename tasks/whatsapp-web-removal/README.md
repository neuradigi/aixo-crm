# WhatsApp Web (unofficial / Baileys) — removal

Remove the unofficial WhatsApp Web provider end-to-end: the Node sidecar, the FastAPI
module, every caller that dispatches to it, its table, its config and its secrets.
WhatsApp Business **Cloud API** (official, Meta) is untouched and remains the only
WhatsApp provider.

## Why

- The product does not use the unofficial provider. It never had an Angular UI
  (`REVIEW_CHECKLIST.md` §K "Known flag at map time": four permission-gated endpoints,
  no component consumes them), so no customer can have connected it through the product.
- It was wired into prod on 2026-11-16 (`3b5c2977`). The prod server receives only the
  `API/` folder, so `../sidecars/whatsapp-web` does not exist there and
  `./run.sh up` failed — prod was down until the sidecar service was removed from
  `docker-compose.prod.yml` (Step 1, below).
- Unofficial WhatsApp clients violate WhatsApp's Terms of Service and put the paired
  number at risk of a ban (unsourced — no `PRODUCT_BRIEF.md` exists; recorded as the
  owner's product decision, not a researched claim).

## Inventory — what exists today

| Area | Location | Fate |
|---|---|---|
| Node sidecar | `sidecars/whatsapp-web/` (whole `sidecars/` folder — it holds nothing else) | delete |
| Prod compose service + volume | `API/docker-compose.prod.yml` `whatsapp-web-sidecar`, `whatsapp_web_sessions` | delete (Step 1, done) |
| Bake entitlement flag | `API/run.sh` `BUILDX_BAKE_ENTITLEMENTS_FS=0` | revert (Step 1, done) |
| Secret forwarding | `API/docker-compose.yml` `*secret-vars`: `WHATSAPP_WEB_SIDECAR_HMAC_SECRET`, `WHATSAPP_WEB_INBOUND_HMAC_SECRET` | delete |
| Config | `API/config.py` `WHATSAPP_WEB_SIDECAR_URL` / `_SIDECAR_HMAC_SECRET` / `_INBOUND_HMAC_SECRET`; `API/config.env` URL + comment block | delete |
| Secrets | `WHATSAPP_WEB_SIDECAR_HMAC_SECRET`, `WHATSAPP_WEB_INBOUND_HMAC_SECRET` in `secrets.prod.enc.env` (the only secrets file carrying them) | remove via `run secrets-edit` on a machine holding the prod age key (user-run; SOPS) |
| Backend module | `API/src/app/core/integrations/whatsapp_web/` (10 files: models, schemas, router, service, data_access, events, sidecar_client, sse_hub, exceptions, `__init__`) | delete |
| Router mount | `API/src/app/core/integrations/router.py` `include_router(whatsapp_web_router)` → `/api/v1/integrations/whatsapp-web/{connect,disconnect,status,events,qr-stream}` | delete |
| Outbound dispatch | `conversations/adapters/whatsapp.py`: `WhatsAppWebAdapter`, the Web fallback in `resolve_whatsapp_adapter`, `resolve_whatsapp_web_adapter`, `_find_active_web_session_id` | delete |
| Media proxy | `conversations/service.py` `open_message_media`: `WhatsAppWebAdapter` guard + `provider_message_id` → Web download branch | delete |
| Chatbot fallback | `chatbots/channel_bridge.py` numbered-text fallback for interactive buttons / list (`_numbered_text_fallback`, `_is_interactive_unsupported`, `fallback_used`) — only ever triggered by `WhatsAppWebAdapter`'s "Cloud API provider" error | delete |
| Provider enum | `IntegrationProvider.whatsapp_web` (Python); `integration_provider` PG enum value | Python: delete. PG: keep (see Decisions) |
| Table | `tbl_whatsapp_web_sessions` (+ RLS policy, `ix_whatsapp_web_sessions_active`) from migration `0141` | drop in new migration |
| Tests | `test_whatsapp_web_{events,events_router,models,service,sidecar_client,sse_hub}.py`; `test_numbered_fallback_shape` in `tests/chatbots/test_nodes_messages.py` | delete |
| Docs / comments | `REVIEW_CHECKLIST.md` §K (header, known flag, K.8–K.14), `DISCOVERY_RULES.md:82`, Baileys wording in `chatbots/nodes/{list,media_button,_shared}.py`, `integrations/models.py` enum docstring, `conversations/service.py` docstrings, `APP/.../media-bubble.component.ts:21` | edit |

**Not in scope — same word, different thing.** "Sidecar" in `integrations/whatsapp/`
(`WhatsAppAccountConfig`, `connect.py`, `embedded_signup.py`, migrations 0061/0089, the
Cloud tests, `whatsapp-card.component.ts`) means the Cloud API per-integration config
row. It stays. `ingest_inbound(pre_parsed=...)` in `conversations/service.py` stays —
`conversations/router.py:1576` uses it for the Cloud webhook path too.

## Decisions

1. **Full removal, not dormancy.** Owner decision (2026-11-25). Dormant code with no UI,
   no deployment and a ToS problem is maintenance cost and attack surface
   (an unauthenticated HMAC-only `/events` endpoint) with no user.
2. **Benchmark (unsourced).** The WhatsApp-native inbox tools named in
   `REVIEW_CHECKLIST.md` §3.1 — Wati, Interakt, Respond.io — and the HubSpot / Zoho /
   Pipedrive WhatsApp integrations connect through the official WhatsApp Business
   Platform only. Removing the unofficial tier brings us in line; it is not a
   deliberate difference to preserve.
3. **Keep the `whatsapp_web` value in the `integration_provider` Postgres enum.**
   Postgres cannot drop an enum value without recreating the type and rewriting
   `tbl_integrations`; 0141's own downgrade made the same call. The new migration
   deletes every `tbl_integrations` row with that provider, and with the Python enum
   member gone nothing can write it again. A stale, unused label is cheaper and safer
   than a type rewrite on a live table.
4. **Conversation history is kept.** Messages that arrived via WhatsApp Web are
   ordinary `channel='whatsapp'` rows; they stay. Their media is served from the
   storage cache if it was ever viewed; otherwise the media proxy returns 410
   ("no longer available"), the same as an expired Meta media id.
5. **Chatbot numbered-text *send* fallback is deleted; numbered *reply* matching is
   kept.** The send fallback is dead once `WhatsAppWebAdapter` is gone (nothing else
   raises the "Cloud API provider" error it catches). The reply matcher
   (`_shared.py` — customer types `1` for button 1) is live behaviour on Cloud that
   costs nothing; only its Baileys wording is fixed.
6. **Migration downgrade recreates an empty table**, schema-identical to 0141
   (columns, constraints, index, RLS policy). Deleted integration rows and session
   rows are not restored — downgrade restores shape, not data.
7. **Order: detach callers → delete module → drop table → infra/docs.** Each step
   leaves the app importable, tests green, and no code referencing something already
   gone.

## Steps

| # | Title | Files (approx.) | Status |
|---|---|---|---|
| 1 | Unhook sidecar from prod deploy (hotfix) | `docker-compose.prod.yml`, `run.sh` | done 2026-11-25, uncommitted |
| 2 | Detach callers — conversations + chatbots stop dispatching to WhatsApp Web | `conversations/adapters/whatsapp.py`, `conversations/service.py`, `chatbots/channel_bridge.py`, `chatbots/nodes/{list,media_button,_shared}.py`, `tests/chatbots/test_nodes_messages.py` | pending |
| 3 | Delete the backend module, its router mount, tests and config | `integrations/whatsapp_web/` (10), `integrations/router.py`, 6 test files, `config.py`, `config.env`, `docker-compose.yml` | pending |
| 4 | Migration `0243_drop_whatsapp_web` + drop `IntegrationProvider.whatsapp_web` | new migration, `integrations/models.py` | pending |
| 5 | Delete `sidecars/`, clean docs/comments, remove SOPS secrets | `sidecars/` (whole), `REVIEW_CHECKLIST.md`, `DISCOVERY_RULES.md`, `media-bubble.component.ts`; user runs `run secrets-edit` for prod | pending |

## Cases

- **An org has a `connected` WhatsApp Web session and no Cloud integration** → after
  Step 2, `resolve_whatsapp_adapter` raises `WhatsAppNotConnected`; outbound WhatsApp
  sends fail with the existing "Connect it in Settings → Integrations" message, same as
  an org that never connected.
- **An org has both Cloud and Web** → Cloud already won dispatch; no change.
- **A message attachment has only `provider_message_id` (Web-origin) and no cached
  copy** → 410, per Decision 4. With a cached copy → served from storage as today.
- **A chatbot run is parked on an interactive node whose last send used the numbered
  fallback** → the customer's `1`/`2` reply still matches (reply matcher kept). New
  sends go as Cloud interactive messages.
- **The sidecar (if one were running anywhere) keeps POSTing `/events`** → after
  Step 3 the route is gone: 404 with no side effect. No deployment runs one
  (prod-neuradigi compose never had it; prod removed in Step 1; local never had it).
- **Two orgs, A had Web rows, B didn't** → the migration deletes by
  `provider = 'whatsapp_web'` across all orgs as the migration role (bypasses RLS by
  design, like every data migration); B is unaffected.
- **Integration row deleted while `tbl_whatsapp_web_sessions` still references it** →
  the FK is `ON DELETE CASCADE`, and the migration drops the sessions table first
  anyway, then deletes the integration rows.
- **Something else references `tbl_integrations` rows with provider `whatsapp_web`**
  (e.g. audit / activity rows by integration id) → Step 4 verifies with a schema query
  for FKs into `tbl_integrations` before writing the delete; any found are handled in
  that step, not assumed away.
- **A dev DB is mid-way (Step 3 shipped, Step 4 not migrated)** → the orphan table
  exists with no model; harmless — nothing queries it.
- **Env still has `WHATSAPP_WEB_*` secrets after Step 3** → unused variables; harmless
  until removed in Step 5.

## Tests

- **Step 1:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`
  lists exactly `api`, `celery`, `celery-beat`, `flower` (+ shared `redis`) and no
  `whatsapp-web-sidecar`; `./run.sh up` on the prod server starts without the
  bake entitlement error.
- **Step 2:** `resolve_whatsapp_adapter` with no Cloud config raises
  `WhatsAppNotConnected` even when a `tbl_whatsapp_web_sessions` row is `connected`
  (asserts the fallback is gone); `open_message_media` on an attachment carrying only
  `provider_message_id` and no cache returns 410; interactive-buttons send on Cloud
  persists the interactive payload with no `fallback` key; button-reply matcher still
  maps `"1"` to the first button; existing Cloud WhatsApp + chatbot suites pass.
- **Step 3:** `grep -r "whatsapp_web\|WHATSAPP_WEB\|sidecar_client" API/src API/config.*`
  is empty (modulo the Python enum member removed in Step 4); app imports;
  `GET /api/v1/integrations/whatsapp-web/status` → 404; layered-architecture and
  table-naming pin-tests pass; full pytest passes.
- **Step 4:** `alembic upgrade head` drops `tbl_whatsapp_web_sessions` and leaves zero
  `tbl_integrations` rows with provider `whatsapp_web`; `alembic downgrade -1`
  recreates the table with its RLS policy (`relrowsecurity` true, policy present) and
  index; upgrade again succeeds; `IntegrationProvider` has exactly
  `google_ads`, `meta_ads`, `whatsapp`.
- **Step 5:** `sidecars/` gone; repo-wide grep for `baileys|whatsapp-web|whatsapp_web`
  (case-insensitive) returns only the historical migrations `0141`/`0142`/`0147`
  and this track folder; `grep WHATSAPP_WEB API/secrets.*.enc.env` is empty (SOPS keeps key names in clear);
  `./run.sh up` still starts cleanly on local.
