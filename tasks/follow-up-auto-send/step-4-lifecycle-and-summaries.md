# Step 4 — Cancel, reschedule guard, housekeeping, summaries

## Goal

A scheduled auto-send can be cancelled, can't be pushed into the past, never outlives its task,
and every follow-up list shows its state.

## Scope

1. `leads/auto_send/service.py`:
   - `cancel_auto_send(session, *, org_id, auto_send_id, actor)` — CAS `scheduled|claimed →
     cancelled` (409 while `sending`), activity, notify creator + assignee.
   - `guard_reschedule(session, *, task, new_due_at)` — 422 `auto_send_past_due`.
   - `housekeep(session)` — cancel `scheduled` rows whose task is closed, undated or retyped.
   - `summaries_for_tasks(session, *, task_ids)` — one query.
2. `leads/router.py` — `POST /leads/auto-sends/{id}/cancel` (`conversations.write` + lead visibility).
3. `tasks/service.py` — `update_task` calls `guard_reschedule` when `due_at` changes.
4. Task list (`tasks/schemas.py` + service) and dashboard followups (`dashboard/schemas.py` +
   service) include `auto_send` summaries.
5. Tests: `API/tests/test_follow_up_auto_send_lifecycle.py`.

## Tests

Cancel works for the creator and a colleague with permission, 404 cross-org, 409 while sending ·
reschedule into the past → 422 · housekeeping cancels rows of done / missed / groomed / undated /
retyped tasks and leaves open ones · summaries come back in one query for 50 tasks.
