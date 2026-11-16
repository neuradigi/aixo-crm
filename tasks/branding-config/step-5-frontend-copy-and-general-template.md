# Step 5 — Frontend product-name copy + base template "General"

**Goal:** no user-visible copy names the product "CRM", "Core CRM" or "FurnitureCRM"; the base template is "General".

## Files

- `features/public/shared/public-shell.component.ts`, `features/public/store/store.component.html`,
  `features/public/listings/listings.component.html` — "Powered by {{ name }}" from `BrandService`.
- `features/pricing/pricing.page.html` — wordmark from `BrandService`.
- `features/user/core/whatsapp/templates/whatsapp-templates.page.html` — "…without leaving {{ name }}".
- `features/user/core/settings/integrations/whatsapp-card.component.html` — placeholder `my-verify-token-xyz123`.
- `assistant-preview.component.html`, `assistant-interface-tab.component.html`,
  `embed-integrations-tab.component.html` — "Powered by {{ name }}".
- `features/user/core/layout/sidebar.component.ts` — `base: 'General'` and the no-template fallback.
- `plan-compare-table.component.ts` — category label "General".
- `API/src/app/core/packs/catalog_config.py`, `API/src/app/packs/base/pack.yaml` — base tile / `display_name` "General".
- `API/tests/test_packs_catalog.py` — expects "General".

## Tests

- `test_packs_catalog` passes with "General"; `npm run build` and eslint clean.
- `git grep -n -E "Powered by (Core )?CRM|leaving Core CRM" APP/src` returns nothing.
