# Step 5 — Sweep: claim, send, compare-and-set, retry, reaper, auto-complete

## Goal

Due auto-sends go out exactly once, fairly across orgs, and every outcome is recorded, shown on
the lead timeline and, when not sent, told to a person.

## Scope

1. `leads/auto_send/data_access.py` — claim query (`FOR UPDATE SKIP LOCKED`, ≤ 25 per org per
   round), CAS updates, reaper queries, message-by-`auto_send_id` lookup.
2. `leads/auto_send/service.py` — `run_sweep(budget_s=45)`: housekeeping → claim rounds → per-row
   fresh session + `set_context(RequestContext(org_id))` → re-checks (task open, `due_at ≤ now`,
   type, lead not won/lost, contact, recipient unchanged, assignee active with
   `conversations.write`, org not read-only, ≤ 6 h late, quiet hours) → CAS `claimed → sending`
   → `send_template_to_contact` → CAS outcome → on `sent` mark the task done via the tasks service
   + lead activity; on `skipped` / `failed` lead activity + bell to the assignee (lead owner if
   the assignee is inactive). 429 → `scheduled` + `not_before` +5 min, max 3 attempts. Reaper:
   `claimed` > 5 min → `scheduled`; `sending` > 15 min → `sent` if a message carries this
   `auto_send_id`, else `failed / interrupted`.
3. `leads/auto_send/tasks.py` — Celery task (thin); `celery_config.py` beat entry (60 s);
   `worker.py` autodiscover.
4. Notification type `follow_up.auto_send_failed` registered in `notifications/event_catalog.py`.
5. Tests: `API/tests/test_follow_up_auto_send_sweep.py`.

## Tests

Two concurrent sweeps send once · fair claim with one org holding 500 due rows · cancel between
claim and send wins · reschedule between claim and send → not sent · sent → task done + activity
· each skip code · 429 retry then fail · reaper both branches · two orgs each use their own
sender.
