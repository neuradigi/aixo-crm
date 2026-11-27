# Step 7 — Due-time reminders for every follow-up

## Goal

The assignee gets a bell when any follow-up (Call included) comes due — once per due time.

## Scope

1. `tasks/models.py` + migration `0246_task_due_reminder` — `tbl_tasks.due_reminder_sent_at`.
2. `tasks/data_access.py` — claim open follow-ups (`followup_type` set) with `due_at` in the last
   hour and no reminder yet, skipping tasks with a pending auto-send (`NOT EXISTS` on
   `tbl_follow_up_auto_sends`); mark reminded.
3. `tasks/service.py` — `send_due_follow_up_reminders()`; `update_task` clears the marker when
   `due_at` changes.
4. `tasks/tasks.py` + beat entry (60 s).
5. Notification type `follow_up.due` registered in `notifications/event_catalog.py`.
6. Tests: `API/tests/test_follow_up_due_reminders.py`.

## Tests

Reminder fires once for a due follow-up · not for a task due 2 h ago (deploy-day flood guard) ·
not for a task with a pending auto-send · rescheduling re-arms it · generic tasks (no
`followup_type`) are ignored.
