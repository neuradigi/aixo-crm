# Step 5 — Delete `sidecars/`, clean docs, host + secrets cleanup

**Goal:** no trace of the provider outside history, migrations and this track.

## Changes (repo)

- Delete `sidecars/` (tracked files; plus untracked `storage/`, `.env`,
  `node_modules/` on this machine).
- `REVIEW_CHECKLIST.md` — line 9 and §K blurb / known flag: drop the Baileys
  mentions; rows K.8–K.14 → `REMOVED` (Decision 11).
- `DISCOVERY_RULES.md:82` — drop "(and the Baileys sidecar)".
- `tasks/design-refresh/step-11-conversations.md:55` — drop the Baileys mention.
- `APP/.../conversations/thread/media-bubble.component.ts:21` — comment wording.

## Owner-run (cannot be done from the repo)

- Prod server: `docker volume ls | grep whatsapp_web` → `docker volume rm <name>` if
  present.
- `./run.sh secrets-edit` (prod env, prod age key) → delete
  `WHATSAPP_WEB_SIDECAR_HMAC_SECRET` and `WHATSAPP_WEB_INBOUND_HMAC_SECRET`.

## Part B check

1. Decisions 11, 12.
2. No code layers touched.
3. Tests: README → Tests → Step 5.
