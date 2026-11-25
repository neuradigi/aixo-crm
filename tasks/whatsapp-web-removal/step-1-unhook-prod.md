# Step 1 — Unhook the sidecar from the prod deploy (hotfix)

**Status:** done — `8b37e925` (2026-11-25).

**Goal:** prod `./run.sh up` starts again.

**Change:** remove the `whatsapp-web-sidecar` service and the `whatsapp_web_sessions`
volume from `API/docker-compose.prod.yml`. The interim `BUILDX_BAKE_ENTITLEMENTS_FS=0`
in `run.sh` was reverted before commit — no build context leaves `API/` any more.

**Verify:** `docker compose -f docker-compose.yml -f docker-compose.prod.yml config`
shows no `whatsapp-web-sidecar`; `./run.sh up` on the prod server starts.
