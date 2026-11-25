# Step 3 — Delete the backend module, its tests and config

**Goal:** the `whatsapp_web` package and its configuration no longer exist.

## Changes

- Delete `API/src/app/core/integrations/whatsapp_web/` (10 files).
- `integrations/router.py` — any remaining reference (import was removed in Step 2).
- Delete `tests/test_whatsapp_web_{events,events_router,models,service,sidecar_client,sse_hub}.py`.
- `config.py` — delete `WHATSAPP_WEB_SIDECAR_URL`, `WHATSAPP_WEB_SIDECAR_HMAC_SECRET`,
  `WHATSAPP_WEB_INBOUND_HMAC_SECRET`.
- `config.env` — delete the WhatsApp Web block.
- `docker-compose.yml` — delete the two `WHATSAPP_WEB_*` entries (and comment) from
  `*secret-vars`.

`IntegrationProvider.whatsapp_web` stays until Step 4 (the DB may still hold rows).

## Part B check

1. Decision 12 covers the file count (pure deletions).
2. No layer changes.
3. Tests: README → Tests → Step 3.
