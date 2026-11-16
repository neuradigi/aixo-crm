# Step 4 — Frontend: single brand from `/app-config`

**Goal:** the Angular app has one brand, whose name and contact addresses come from `/app-config`.

## Files

- `APP/src/app/core/constants/brands.ts` — deleted.
- `APP/src/app/core/services/brand.service.ts` — computed view over `AppConfigApiService.config()`:
  `name` (fallback: the `index.html` title captured at construction), `logoUrl = 'images/logo.png'`,
  `supportEmail` / `privacyEmail` (null when unavailable). No favicon/manifest rewriting; the document
  title is set once config has loaded.
- `APP/src/app/schemas/common.ts` — `IAppConfig` gains `app_name`, `support_email`, `privacy_email`.
- `APP/src/app/app.config.ts` — apply the title after `appConfigApi.load()`.
- `footer.component.html/.ts` — `© {year} {name}`; support/privacy links from `BrandService`, hidden when null.
- `data-deletion-status.component.html/.ts` — privacy address from `BrandService`.
- `welcome.component.html` — drop the "FurnitureCRM is being built…" line.
- `APP/src/main.ts` — `tracePropagationTargets: ['localhost', deriveApiOrigin()]`.
- `APP/src/environments/environment*.ts` — `embedWidgetHost` derived from the API origin in prod builds
  (dev keeps `http://localhost:5173`).
- `APP/public/brands/` — deleted.

## Tests

- `npm run build` (production) and `ng build --configuration development`; `tsc --noEmit`; eslint.
- Built `dist/` contains no `neuradigi` outside `3rdpartylicenses.txt`.
- Visual: footer "© 2026 AIXO CRM" with working support/privacy links; tab title "AIXO CRM".
