# Step 1 — Brand assets at the default paths

**Goal:** every brand asset the browser loads is AIXO's, at the paths that remain after the hostname
resolver is removed (Step 4), so no deploy between steps shows Neuradigi.

## Files

- `APP/public/favicon.ico` ← `APP/public/brands/aixo/favicon.ico`
- `APP/public/icons/icon-*.png` (8) ← `APP/public/brands/aixo/icons/icon-*.png`
- `APP/public/images/logo.png` (new) ← `APP/public/brands/aixo/Logo.png`
- `APP/public/images/Logo.svg` — replaced by a 914×240 SVG embedding `logo.png` as a base64 data URI (D11)
- `APP/public/manifest.webmanifest` — `name` "AIXO CRM", `short_name` "AIXO" (icons, `scope`, `start_url` unchanged)
- `APP/src/index.html` — `<title>AIXO CRM</title>`

`public/brands/` stays until Step 4 (the AIXO entry in `brands.ts` still points at it).

## Tests / verify

- No file under `APP/public/` outside `brands/` has a pre-track Neuradigi blob hash (list in Step 10).
- Every path referenced by `index.html`, `manifest.webmanifest`, `ngsw-config.json`, `brands.ts` exists.
- `npm run build` succeeds.
- Visual: login-page logo, browser-tab favicon and `/admin` layout logo all show AIXO.
