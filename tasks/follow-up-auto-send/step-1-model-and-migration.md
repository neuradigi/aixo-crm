# Step 1 — `core/leads/auto_send/` model + migration `0245` + DAL

## Goal

The table that records "send template T to this lead's contact when follow-up task X comes due",
with every constraint, cascade and index later steps rely on.

## Scope

1. `API/src/app/core/leads/auto_send/__init__.py`, `models.py`:
   - Enums `FollowUpAutoSendStatus` (`scheduled, claimed, sending, sent, failed, skipped,
     cancelled`) and `FollowUpAutoSendChannel` (`whatsapp, email`) as PG enums
     `follow_up_auto_send_status` / `follow_up_auto_send_channel`.
   - `FollowUpAutoSend` (`tbl_follow_up_auto_sends`, `TenantScoped`): `task_id` unique FK
     `tbl_tasks` ON DELETE CASCADE; `lead_id` FK `tbl_leads` ON DELETE CASCADE; `template_id`
     FK `tbl_message_templates` ON DELETE SET NULL; `template_name`; `channel`; `recipient`;
     `status` (default `scheduled`); `reason`; `claim_token`; `claimed_at`; `attempts`
     (default 0); `not_before`; `message_id` FK `tbl_messages` ON DELETE SET NULL; `sent_at`;
     `created_by_id`; `cancelled_by_id`; `cancelled_at`; `created_at`; `updated_at`.
   - Indexes: partial `(status, not_before) WHERE status IN ('scheduled','claimed','sending')`
     for the sweep; `(org_id, lead_id)` for per-lead / per-person lookups.
2. `API/alembic/versions/0245_follow_up_auto_sends.py` — enums, table, indexes, RLS
   (`apply_rls`); downgrade drops all of it.
3. `API/src/app/core/leads/auto_send/data_access.py` — `insert_auto_send`,
   `get_auto_send_for_task`, `list_pending_auto_sends_for_contact` (joins `tbl_leads` on
   `contact_id`; pending = `scheduled | claimed | sending`).
4. Tests: `API/tests/test_follow_up_auto_send_model.py`.

## Tests

Table follows the `tbl_` pin-test · migration up / down / up on the test DB · RLS policy present ·
deleting the task deletes the row · deleting the lead deletes the row · deleting the template
nulls `template_id` · a second row for the same task violates the unique constraint ·
`list_pending_auto_sends_for_contact` finds a pending row through either of the contact's leads
and ignores `sent` / `cancelled` rows.
