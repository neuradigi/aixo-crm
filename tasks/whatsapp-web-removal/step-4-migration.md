# Step 4 — Migration + drop the Python enum member

**Goal:** the database holds no WhatsApp Web state and refuses to store it again.

## Pre-flight (owner runs on every prod DB before `./run.sh upgrade`)

```sql
SELECT 'integrations' AS what, status::text, count(*) FROM tbl_integrations
 WHERE provider = 'whatsapp_web' GROUP BY status
UNION ALL
SELECT 'sessions', status, count(*) FROM tbl_whatsapp_web_sessions GROUP BY status
UNION ALL
SELECT 'dlq', NULL, count(*) FROM tbl_integration_dlq WHERE provider = 'whatsapp_web'
UNION ALL
SELECT 'web_routed_conversations', NULL, count(*) FROM tbl_conversations c
  JOIN tbl_whatsapp_web_sessions s
    ON s.org_id = c.org_id AND s.phone_number = c.received_via_phone_id;
```

Every count zero (the `integrations` / `sessions` lines return no rows at all) →
migrate. Any `sessions` row in `connected` / `pairing` / `reconnecting` → stop
(Decision 9). Other non-zero counts are what the migration cleans up — note them.

## Migration (`0243_drop_whatsapp_web`, next free number)

Upgrade, in order:
1. `UPDATE tbl_conversations SET received_via_phone_id = NULL` where it equals a
   session `phone_number` in the same org and is not a Cloud `phone_id` in that org.
2. Drop the RLS policy, index and `tbl_whatsapp_web_sessions`.
3. `DELETE FROM tbl_integration_dlq WHERE provider = 'whatsapp_web'`.
4. `DELETE FROM tbl_integrations WHERE provider = 'whatsapp_web'`.
5. Add `ck_integrations_provider_not_whatsapp_web` and
   `ck_integration_dlq_provider_not_whatsapp_web`.

Downgrade: drop the two CHECKs; recreate the table exactly as 0141 (Decision 6).

## Code

- `integrations/models.py` — remove `IntegrationProvider.whatsapp_web`; docstring.
- Search the code for JSONB readers of `integration_id`; record the finding.

## Part B check

1. Decisions 3, 6, 8, 9, 13.
2. Migration only + model enum; `tbl_` names unchanged.
3. Tests: README → Tests → Step 4 (throwaway Postgres 17).
