# Step 10 — Own send time for the auto-message

## Goal

Staff choose when the auto-message goes: at the follow-up time (default) or at a time they pick.

## Scope

1. Migration `0247`: nullable `tbl_follow_up_auto_sends.send_at`. NULL = send at the follow-up's
   live due time and move with it on reschedule (today's behaviour, every existing row).
2. `NextFollowUpSpec.auto_send_at` (needs `auto_send_template_id`); `stage_auto_send(send_at=)`
   runs the past / 90-day / quiet-hours checks on the effective send time and stores it.
3. Effective send time `coalesce(send_at, task.due_at)` everywhere it matters: sweep candidates
   and ordering, send-time verdict (release / too late), summaries (`due_at` = when it sends),
   the modal's "already scheduled" banner.
4. Reschedule guard: a row with its own time only stops the follow-up losing its date.
5. Update Status picker: "When to send" (At the follow-up time / At a different time) + date
   picker starting at the follow-up time; "Scheduled when you save · sends …"; Save blocked
   until a picked time is set.

## Tests

Own time stored and checked instead of the follow-up's · own past / too-far time refused · guard
lets the follow-up move when the message has its own time, still refuses clearing the date ·
sweep sends on the own time and releases one still in the future · picker emits the ISO time and
blocks Save while the time is empty.
