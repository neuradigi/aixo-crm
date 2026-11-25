# Step 2 — Detach callers and unmount the router

**Goal:** nothing in the running app dispatches to, reads from, or exposes WhatsApp Web.
The module still exists on disk (deleted in Step 3) so this step stays small.

## Changes

- `integrations/router.py` — remove `router.include_router(whatsapp_web_router)` and
  its import + comment. `/api/v1/integrations/whatsapp-web/*` → 404.
- `conversations/adapters/whatsapp.py` — delete `WhatsAppWebAdapter`,
  `resolve_whatsapp_web_adapter`, `_find_active_web_session_id`, the Web fallback in
  `resolve_whatsapp_adapter`; return type becomes `WhatsAppAdapter`; docstrings and
  `__all__` updated.
- `conversations/service.py` — `open_message_media`: drop the `WhatsAppWebAdapter`
  guard and the `provider_message_id` branch; an attachment without a Cloud media id
  raises `WhatsAppMediaUnavailable` → 410 before any provider call. Imports + Baileys
  wording in docstrings.
- `workflows/actions/send.py` — `send_whatsapp`: drop the `isinstance` check and the
  plain-text `else` branch; always the Cloud template path.
- `chatbots/channel_bridge.py` — interactive buttons / list sends: drop the
  numbered-text fallback, `_numbered_text_fallback`, `_is_interactive_unsupported`,
  `fallback_used`.
- `chatbots/nodes/{list,media_button,_shared}.py` — wording only (reply matcher kept).
- Tests: delete `test_numbered_fallback_shape`; add the Step 2 assertions from the
  README Tests section.

## Part B check

1. Contradicts no Decision (5, 4, 10).
2. Layers: router change is mount-only; service/adapter changes stay in their layer.
3. Tests: README → Tests → Step 2.
