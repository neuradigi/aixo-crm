# Step 10 — CI guard + DB audit query

**Goal:** a legacy brand cannot come back without failing CI, and the operator can find legacy values in data.

## Files

- `.github/scripts/check_branding.py` (stdlib only) — reads `git ls-files` and runs the checks in the
  README's "CI guard" section: banned terms with the per-line allowlist, pre-track image blob hashes,
  title / manifest == `APP_NAME`, `APP_NAME` absent from `config.<env>.env`, `environment.ts` API origin ==
  `config.prod.env` `API_BASE_URL`, at least 500 files scanned.
- `.github/workflows/quality.yml` — new `branding` job running it on PRs to `dev` / `main`.
- `tasks/branding-config/db-audit.sql` — read-only: every `text` / `varchar` / `jsonb` column in `public`
  matching `neuradigi|furniturecrm|core-crm\.com|yourcrm`, plus admin / owner accounts whose email domain
  is not `aixoapp.com`.

Pre-track Neuradigi image blob hashes (`git hash-object`, recorded 2026-11-17 at `718c7ecb`):

```
2bb3c4ec4fe6820d082679c84a59d5582180d1cf
25b80d04438be46af47546830cc9e2afccf746a6
0b51d2e5cb60bbebc15d28f6b5762671931e1c50
bd38d797399d87c9cff6d56d16b16958ec412954
4f23c041aa13aa8207b314c3eb858a3967b0c95a
8d4c7af085a0265aad1cc38b5f7c0b082441be6d
6921b92ebd98ba836f853e7933aae75e0bcf54e3
d9bb7e2c8bff57a3781ce95465c071de9d2d7a33
8d32d97e76906a7bb0478ed7526827fd289493ec
c6093539fe6240799239a2901fda5dc4783d39e1
```

## Tests

- The guard passes on the branch.
- Each seeded violation fails it: a banned word in a new file, a pre-track image, a title mismatch,
  `APP_NAME` in `config.prod.env`, an API-origin mismatch.
