# WhatsApp Web (unofficial / Baileys) — removal

Remove the unofficial WhatsApp Web provider end-to-end: the Node sidecar, the FastAPI
module, every caller that dispatches to it, its table, its config and its secrets.
WhatsApp Business **Cloud API** (official, Meta) is untouched and remains the only
WhatsApp provider.

## Why

- The product does not use the unofficial provider. It never had an Angular UI
  (`REVIEW_CHECKLIST.md` §K "Known flag at map time": four permission-gated endpoints,
  no component consumes them). The endpoints were reachable over HTTP by anyone holding
  `settings.integrations.manage`, so "nobody connected it" is checked against prod data
  in Step 4, not assumed.
- It was wired into prod on 2026-11-16 (`3b5c2977`). The prod server receives only the
  `API/` folder, so `../sidecars/whatsapp-web` does not exist there and
  `./run.sh up` failed — prod was down until the sidecar service was removed from
  `docker-compose.prod.yml` (Step 1, committed in `8b37e925`).
- A `whatsapp_web` row in `tbl_integrations` already breaks `GET /api/v1/integrations`:
  `IntegrationProviderLiteral` (`integrations/schemas.py:26`) excludes it, so the
  response model fails to validate. Removing the provider fixes a latent 500.
- Unofficial WhatsApp clients violate WhatsApp's Terms of Service and put the paired
  number at risk of a ban (unsourced — no `PRODUCT_BRIEF.md` exists; recorded as the
  owner's product decision, not a researched claim).

## Inventory — what exists today

| Area | Location | Fate |
|---|---|---|
| Node sidecar | `sidecars/whatsapp-web/` (whole `sidecars/` folder — it holds nothing else) | delete, incl. untracked `storage/`, `.env`, `node_modules/` |
| Prod compose service + volume | `API/docker-compose.prod.yml` `whatsapp-web-sidecar`, `whatsapp_web_sessions` | deleted (Step 1) |
| Bake entitlement flag | `API/run.sh` `BUILDX_BAKE_ENTITLEMENTS_FS=0` | never committed (Step 1) |
| Docker volume on host | `*_whatsapp_web_sessions` on the prod server, if it was ever created | `docker volume rm` (Step 5, user-run) |
| Secret forwarding | `API/docker-compose.yml` `*secret-vars`: `WHATSAPP_WEB_SIDECAR_HMAC_SECRET`, `WHATSAPP_WEB_INBOUND_HMAC_SECRET` | delete |
| Config | `API/config.py` `WHATSAPP_WEB_SIDECAR_URL` / `_SIDECAR_HMAC_SECRET` / `_INBOUND_HMAC_SECRET`; `API/config.env` URL + comment block | delete |
| Secrets | both keys in `secrets.prod.enc.env` (the only secrets file carrying them) | remove via `run secrets-edit` on a machine holding the prod age key (Step 5, user-run) |
| Backend module | `API/src/app/core/integrations/whatsapp_web/` (10 files) | delete |
| Router mount | `integrations/router.py` `include_router(whatsapp_web_router)` → `/api/v1/integrations/whatsapp-web/{connect,disconnect,status,events,qr-stream}` | unmount in Step 2, file deleted in Step 3 |
| Outbound dispatch | `conversations/adapters/whatsapp.py`: `WhatsAppWebAdapter`, the Web fallback in `resolve_whatsapp_adapter` (+ its `WhatsAppAdapter \| WhatsAppWebAdapter` return type), `resolve_whatsapp_web_adapter`, `_find_active_web_session_id` | delete |
| Workflow send | `workflows/actions/send.py:463` — `isinstance(adapter, WhatsAppAdapter)` with an `else: adapter.send(...)` branch only `WhatsAppWebAdapter` can reach | collapse to the Cloud path |
| Media proxy | `conversations/service.py` `open_message_media`: `WhatsAppWebAdapter` guard + `provider_message_id` → Web download branch | delete; explicit 410 |
| Chatbot fallback | `chatbots/channel_bridge.py` numbered-text fallback for interactive buttons / list (`_numbered_text_fallback`, `_is_interactive_unsupported`, `fallback_used`) — only triggered by `WhatsAppWebAdapter`'s "Cloud API provider" error | delete |
| Provider enum | `IntegrationProvider.whatsapp_web` (Python); `integration_provider` PG enum value | Python: delete. PG: keep + `CHECK` (Decision 3) |
| Enum-typed columns | `tbl_integrations.provider`, `tbl_integration_dlq.provider` (`ON DELETE SET NULL` FK — a DLQ row survives its integration's delete) | migration deletes `whatsapp_web` rows from both |
| Conversation routing | `tbl_conversations.received_via_phone_id` holding a Web session's `phone_number` (stamped by `whatsapp_web/events.py:292`, never rewritten) | migration clears it (Decision 8) |
| Table | `tbl_whatsapp_web_sessions` (+ RLS policy, `ix_whatsapp_web_sessions_active`) from migration `0141` | drop in new migration |
| Tests | `test_whatsapp_web_{events,events_router,models,service,sidecar_client,sse_hub}.py`; `test_numbered_fallback_shape` in `tests/chatbots/test_nodes_messages.py` | delete |
| Docs / comments | `REVIEW_CHECKLIST.md` §K (module blurb, known flag, K.8–K.14), `DISCOVERY_RULES.md:82`, `REVIEW_CHECKLIST.md:9`, `tasks/design-refresh/step-11-conversations.md:55`, Baileys wording in `chatbots/nodes/{list,media_button,_shared}.py`, `integrations/models.py` enum docstring, `conversations/service.py` docstrings, `APP/.../media-bubble.component.ts:21` | edit |

**Not in scope — same word, different thing.** "Sidecar" in `integrations/whatsapp/`
(`WhatsAppAccountConfig`, `connect.py`, `embedded_signup.py`, migrations 0061/0089, the
Cloud tests, `whatsapp-card.component.ts`, `integrations-api.service.ts`) means the Cloud
API per-integration config row. It stays. `receive_webhook(pre_parsed=...)` in
`conversations/service.py` stays — `conversations/router.py:1576` uses it for the Cloud
webhook, after that route's signature check.

## Decisions

1. **Full removal, not dormancy.** Owner decision (2026-11-25). Dormant code with no UI,
   no deployment and a ToS problem is maintenance cost and attack surface
   (an HMAC-only `/events` endpoint) with no user.
2. **Benchmark (unsourced).** The WhatsApp-native inbox tools named in
   `REVIEW_CHECKLIST.md` §3.1 — Wati, Interakt, Respond.io — and the HubSpot / Zoho /
   Pipedrive WhatsApp integrations connect through the official WhatsApp Business
   Platform. The Web tier existed for orgs "that don't have Meta approval yet"; the
   official answer to that is Meta's **Business App coexistence** onboarding via
   Embedded Signup (a number already on the WhatsApp Business App joins the Cloud API
   and keeps the phone app). We do not support coexistence today. It is recorded as a
   **follow-up needing Gate 0 discovery**, not part of this track. Removing the Web
   tier opens no new product gap — it never had a UI.
3. **Keep the `whatsapp_web` value in the `integration_provider` Postgres enum, and
   forbid it with `CHECK` constraints.** Postgres cannot drop an enum value without
   recreating the type and rewriting live tables; 0141's own downgrade made the same
   call. The migration deletes every row carrying the value from both enum-typed
   tables, then adds `CHECK (provider <> 'whatsapp_web')` to `tbl_integrations` and
   `tbl_integration_dlq`, so the database — not just the Python enum — guarantees no
   row can carry it again.
4. **Conversation history is kept.** Messages that arrived via WhatsApp Web are
   ordinary `channel='whatsapp'` rows; they stay. Their media is served from the
   storage cache if it was ever viewed; otherwise the media proxy returns 410
   ("no longer available") **explicitly**, before any provider call — an attachment
   with no Cloud `media_id` never reaches the Cloud adapter.
5. **Chatbot numbered-text *send* fallback is deleted; numbered *reply* matching is
   kept.** The send fallback is dead once `WhatsAppWebAdapter` is gone (nothing else
   raises the "Cloud API provider" error it catches; nothing outside `channel_bridge.py`
   reads `fallback` / `fallback_used`). The reply matcher (`_shared.py` — customer types
   `1` for button 1) is live behaviour on Cloud and stays; only its Baileys wording is
   fixed. **Known gap, recorded not fixed:** chatbot triggers allow `channel = any`, and
   the Facebook / Instagram / SMS adapters take no `interactive` argument, so a buttons
   or list node on those channels fails rather than degrading to numbered text. A
   capability-keyed fallback is a separate track.
6. **Migration downgrade recreates an empty table**, schema-identical to 0141
   (columns, constraints, index, `ENABLE ROW LEVEL SECURITY` — 0141 did not `FORCE` —
   and the `tbl_whatsapp_web_sessions_tenant_isolation` policy with the same `USING`
   and `WITH CHECK`), and drops the two `CHECK` constraints. Deleted rows and cleared
   `received_via_phone_id` values are not restored — downgrade restores shape, not data.
7. **Audit-log rows are kept.** `integrations.whatsapp_web.*` audit entries are
   append-only history; their `entity_type` / ids are plain strings nothing resolves.
8. **Clear `received_via_phone_id` on Web-origin conversations.** The send path passes
   that value as `phone_id`, the resolver finds no Cloud config for a Web number and
   raises "phone … is not connected" — so those threads could never be answered, even
   after the org connects Cloud. The migration sets it to `NULL` where it equals a
   `tbl_whatsapp_web_sessions.phone_number` in the same org **and** is not any Cloud
   `tbl_whatsapp_account_configs.phone_id` in that org, **before** dropping the
   sessions table (the only lookup that identifies them). `NULL` routes replies through
   the org's default Cloud number.
9. **Prod data is counted before the migration runs.** Step 4 ships a read-only
   pre-flight query the owner runs on every prod DB. Zero rows → migrate. Any session in
   `connected` / `pairing` / `reconnecting` → stop and decide (logout, owner notice)
   before migrating.
10. **Order: detach callers (+ unmount router) → delete module → migration → infra /
    docs.** Each step leaves the app importable, tests green, and no code referencing
    something already gone. Deploy order is separate — see below.
11. **Checklist IDs are stable.** `REVIEW_CHECKLIST.md` rows K.8–K.14 get status
    `REMOVED` (with the track name), not deleted or renumbered — code comments cite
    checklist IDs.
12. **Step size.** Steps 3 and 5 exceed rule 8's ~10-file guide. Both are pure
    deletions plus one-line edits — reviewable in minutes — so they are not split.
13. **Migration number** is the next free one when Step 4 is implemented (currently
    `0243`); Step 4 confirms a single Alembic head.

## Deploy order (prod)

`./run.sh up` does not migrate; `./run.sh migrate` is a separate manual command.

1. Deploy Steps 2 + 3 code together → `./run.sh up`. Nothing queries
   `tbl_whatsapp_web_sessions` any more; the Python enum still accepts `whatsapp_web`.
2. Run the Step 4 pre-flight query on the DB. Zero risky rows → `./run.sh migrate`.
3. Deploy Step 4 + 5 code → `./run.sh up` (Python enum member gone; DB already clean).

Deploying all steps at once is safe **only** if `./run.sh migrate` runs before the new
containers serve traffic; with the documented order there is no window where code and
schema disagree.

## Steps

| # | Title | Files | Status |
|---|---|---|---|
| 1 | Unhook sidecar from prod deploy (hotfix) | `docker-compose.prod.yml` | done — `8b37e925` |
| 2 | Detach callers + unmount the router | `integrations/router.py`, `conversations/adapters/whatsapp.py`, `conversations/service.py`, `workflows/actions/send.py`, `chatbots/channel_bridge.py`, `chatbots/nodes/{list,media_button,_shared}.py`, tests | done — `fe8138da` |
| 3 | Delete the backend module, its tests and config | `integrations/whatsapp_web/` (10), `integrations/router.py` import, 6 test files, `config.py`, `config.env`, `docker-compose.yml` | done — `3f41b879` |
| 4 | Migration: clear routing, delete rows, drop table, add CHECKs; drop `IntegrationProvider.whatsapp_web` | new migration, `integrations/models.py`, pre-flight SQL | done — prod pre-flight + migrate pending (owner) |
| 5 | Delete `sidecars/`, docs/comments, host + secrets cleanup | `sidecars/`, `REVIEW_CHECKLIST.md`, `DISCOVERY_RULES.md`, `tasks/design-refresh/step-11-conversations.md`, `media-bubble.component.ts`; user-run volume + SOPS commands | done — volume check + SOPS key removal pending (owner) |

## Cases

- **Org has a `connected` Web session and no Cloud** → caught by the Step 4 pre-flight
  before any data changes (Decision 9). If it reaches code: after Step 2,
  `resolve_whatsapp_adapter` raises `WhatsAppNotConnected` → "Connect it in Settings →
  Integrations".
- **Org has both Cloud and Web; conversation started on Web** → today replies already
  fail ("phone … is not connected") because `received_via_phone_id` holds the Web
  number. After Step 4 the value is cleared and replies go out from the default Cloud
  number (Decision 8). The customer may see a different sender number; the 24-hour
  window rules apply as for any Cloud conversation.
- **Org has both; conversation started on Cloud** → unchanged.
- **Agent quotes or reacts to an old Web-origin message from Cloud** → the outbound
  carries a Baileys message id as `context.message_id`; Meta rejects it and the send
  surfaces the existing `WhatsAppSendError` to the agent. Not special-cased.
- **Attachment with only `provider_message_id` (Web-origin), no cached copy** → 410
  with no outbound HTTP call. With a cached copy → served from storage.
- **Chatbot run parked on an interactive node whose last send used the numbered
  fallback** → the customer's `1`/`2` reply still matches (matcher kept); parked runs
  expire via the existing `sweep_chatbot_waits` / `expires_at`.
- **A sidecar (anywhere) keeps POSTing `/events`** → after Step 2 the route is
  unmounted: 404, no side effect. No deployment runs one (prod-neuradigi compose never
  had it; prod removed in Step 1; local never had it).
- **Two orgs, A had Web rows, B didn't** → the migration deletes by
  `provider = 'whatsapp_web'` / joins on `org_id`; B is unaffected. The migration runs
  as the table owner (`DB_USER=postgres` in prod), so RLS (`ENABLE`, not `FORCE`) does
  not filter its writes; the Step 4 test checks counts from a fresh connection.
- **DLQ row for a `whatsapp_web` integration** → its FK is `SET NULL`, so it would
  survive the integration delete with the enum value still set; the migration deletes
  it explicitly (WhatsApp Web never wrote DLQ rows, so expected count is zero).
- **Integration row deleted while `tbl_whatsapp_web_sessions` references it** → the FK
  is `ON DELETE CASCADE`; the migration drops the sessions table first anyway.
- **Something stores an integration id in JSONB** (workflow / chatbot / automation
  config, activity payloads) → Step 4 greps the code for JSONB `integration_id`
  readers and records the result; any resolver without an `org_id` filter is fixed
  there.
- **Dev DB mid-way (Step 3 shipped, Step 4 not migrated)** → orphan table with no
  model; harmless — nothing queries it.
- **Paired phone still lists a "Linked device"** → only possible if a sidecar ever ran
  and paired; the pre-flight surfaces it. The owner unlinks it from the phone
  (WhatsApp → Linked devices); no sidecar exists to call logout.
- **Another branch lands migration 0243 first** → Step 4 checks `alembic heads`
  shows exactly one head and renumbers if not.

## Tests

- **Step 1:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`
  lists no `whatsapp-web-sidecar`; `./run.sh up` on the prod server starts.
- **Step 2:**
  - `resolve_whatsapp_adapter` with no Cloud config raises `WhatsAppNotConnected` and
    issues no query against `tbl_whatsapp_web_sessions`.
  - `open_message_media` on an attachment carrying only `provider_message_id`, no
    cache → 410, and `resolve_whatsapp_adapter` / any adapter download is never called.
  - interactive-buttons and list sends on Cloud persist the interactive payload with no
    `fallback` key; an adapter error propagates instead of being swallowed.
  - workflow `send_whatsapp` with a Cloud adapter sends the approved template (existing
    behaviour) — the removed `else` branch leaves no plain-text path.
  - button-reply matcher still maps `"1"` to the first button.
  - `POST` and `GET` on `/api/v1/integrations/whatsapp-web/{events,status}` → 404.
  - existing Cloud WhatsApp, chatbot, workflow and layered-architecture tests pass.
- **Step 3:** `grep -rn "whatsapp_web\|WHATSAPP_WEB\|sidecar_client"` over `API/src`,
  `API/config*`, `API/docker-compose*.yml` returns only the `IntegrationProvider`
  member (removed in Step 4); app imports; full pytest passes.
- **Step 4:**
  - `alembic heads` → exactly one head.
  - On a throwaway Postgres 17 seeded with one org holding a Web integration + session
    (phone `X`), a Cloud config (phone_id `P`), a conversation with
    `received_via_phone_id = X`, another with `= P`, and a DLQ row with provider
    `whatsapp_web`: `upgrade head` → sessions table gone; zero `whatsapp_web` rows in
    `tbl_integrations` and `tbl_integration_dlq`; conversation `X` is `NULL`,
    conversation `P` unchanged; inserting a `whatsapp_web` integration fails the CHECK.
  - `downgrade -1` → table back with `relrowsecurity = true`, policy `qual` and
    `with_check` equal to 0141's, index present, CHECKs gone; `upgrade head` again
    succeeds.
  - `IntegrationProvider` has exactly `google_ads`, `meta_ads`, `whatsapp`.
- **Step 5:** `sidecars/` gone (tracked and untracked); repo-wide case-insensitive grep
  for `baileys|whatsapp-web|whatsapp_web` returns only migrations `0141`/`0142`/`0147`,
  the Step 4 migration, `REVIEW_CHECKLIST.md`'s `REMOVED` rows and this track folder;
  `grep WHATSAPP_WEB API/secrets.*.enc.env` is empty (SOPS keeps key names in clear);
  `docker volume ls | grep whatsapp_web` empty on the prod server.

## Review log

Plan reviewed 2026-11-25 by three independent reviewers (attacker / architect /
absence) per `PLANNING_RULES.md` Part C; owner accepted all findings. Severity
disagreement recorded: the attacker rated the still-mounted `/events` route High; the
verifier fails closed on an empty secret, compares in constant time and needs an
existing session row, so it is Low — unmounting moved into Step 2 regardless.
