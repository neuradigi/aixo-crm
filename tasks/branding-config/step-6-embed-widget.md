# Step 6 — Embed widget: platform name from the API, host from its own script URL

**Goal:** the widget bundle carries no product name and no domain.

## Files

- `API/src/app/core/embed/schemas.py` — `WidgetConfigPublic.platform_name: str`.
- `API/src/app/core/embed/service.py` — populate from `APP_NAME`.
- `API/src/app/core/ai_assistants/public_router.py` — `_PublicAssistantMeta.platform_name` (populated in its service).
- `widget/src/types.ts`, `widget/src/renderer.ts`, `widget/src/chat.ts` — render `Powered by ${platform_name}`;
  omit the label when absent.
- `widget/src/loader.ts` — default host from `new URL(document.currentScript.src).origin`; an explicit
  `data-host` still wins.
- `widget/dist/v1/widget.js` — rebuilt (`npm run build`).
- Tests: API test for both payloads; widget vitest for the footer and host derivation.

## Tests

- Both public payloads include `platform_name == APP_NAME`.
- Widget: footer reads `Powered by AIXO CRM`; label omitted when `platform_name` is missing; default host == script origin.
- Bundle stays under the `scripts/check-size.ts` budget.
