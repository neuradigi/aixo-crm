# Step 3 — Scheduling in log-update + `GET /leads/{id}/auto-send`

## Goal

Update Status can attach an auto-send to the follow-up it creates, with every rule checked in the
same transaction, and the modal can see a person's pending auto-send before saving.

## Scope

1. `leads/schemas.py` — `NextFollowUpSpec.auto_send_template_id: UUID | None`,
   `replace_existing_auto_send: bool = False` (nested `extra="forbid"`); response adds
   `auto_send` summary; `AutoSendSummary` schema.
2. `leads/auto_send/service.py` — `stage_auto_send(session, *, org_id, lead, task, template_id,
   actor, replace)`: `conversations.write`; type is whatsapp/email; template checks (shared with
   Step 2); recipient present and not suppressed; sender / number exists; lead not being closed
   in this save; `due_at` ≥ now − 5 min and ≤ now + 90 days; marketing template not inside quiet
   hours (org settings, category bypass); per-user cap 100 scheduled per rolling day; contact row
   locked, then one-pending-per-person check across the contact's leads → 409
   `auto_send_exists` {due_at, template_name, created_by} unless `replace`, which cancels the old
   one. Inserts the row + "Auto follow-up scheduled" lead activity + audit.
3. `leads/service.py` — `log_update_for_lead` calls it after the task insert; post-commit notify
   the previous creator when replaced.
4. `leads/router.py` — `GET /leads/{id}/auto-send` (pending auto-send for this lead's person).
5. Quiet-hours check: public function in the settings / workflows compliance module (no copy).
6. Tests: `API/tests/test_follow_up_auto_send_schedule.py`.

## Tests

Schedule creates task + row in one commit · each rejection code · Replace cancels the old row and
creates the new one · concurrent schedules for one person → one 200, one 409 · template from
another org → 422 · without `conversations.write` → 403 and no task · GET returns the pending row
from the person's other lead.
