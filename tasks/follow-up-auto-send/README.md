# Follow-up auto-send — send a saved template when a lead follow-up comes due

Client request (2026-11-27): when a lead says "call me later" or "message me on Tuesday", staff log
a follow-up in **Update Status**. On that date the system should **automatically send the lead a
saved template** (approved WhatsApp template or email template). Today a follow-up only creates a
task on the dashboard; nothing is sent, and nothing fires when the task comes due.

Owner decisions (2026-11-27):
- Template picked **per follow-up, in the Update Status modal**, optional, only for WhatsApp / Email
  follow-ups. UI uses the app's current components (`crm-mobile-select`, `crm-mobile-datetime`).
- After a successful send the follow-up is **marked done** automatically.
- If the lead **messages us first**, the scheduled send is **cancelled** and the assignee told.
- Staff get a **bell reminder when any follow-up comes due** (Call included).

> **Revised 2026-11-27** after the Part C reviewer gate (Attacker · Architect · Absence). Owner
> accepted every safety fix. Disagreements recorded under Decisions.

## What exists today

| Concept | Shape | Cite |
|---|---|---|
| Follow-up | `tbl_tasks`: `related_entity_type='lead'`, `related_entity_id`, `due_at`, `followup_type`, `status ∈ {open,done,cancelled,missed}`, `assigned_to_id`. No `created_by`, no `contact_id`, **no FK to leads** | [`tasks/models.py:31-138`](../../API/src/app/core/tasks/models.py#L31) |
| Update Status write | `POST /leads/{id}/log-update`, one transaction (contact basics, stage, note, task insert), then `notify_task_created` | [`leads/router.py:506-544`](../../API/src/app/core/leads/router.py#L506), [`leads/service.py:1860-2073`](../../API/src/app/core/leads/service.py#L1860) |
| Many open follow-ups per lead | allowed; modal pre-fills due = now + 2 h | [`update-status-modal.component.ts:562`](../../APP/src/app/features/user/core/leads/update-status-modal.component.ts#L562) |
| Task changes | complete (single/bulk), reopen, reschedule (no bounds), reassign, hard delete, mark-missed; nightly groom = raw bulk `UPDATE` (bypasses service hooks) | [`tasks/service.py:494-923`](../../API/src/app/core/tasks/service.py#L494), [`tasks/tasks.py:63`](../../API/src/app/core/tasks/tasks.py#L63) |
| WhatsApp one-off template send | `conversations.service.send_template_message` — needs conversation + `user_id`; block list; approved + active; contact/org vars; message row; audit; commits; raises plain `ValueError` / `HTTPException`; no opt-out check | [`conversations/service.py:779-1004`](../../API/src/app/core/conversations/service.py#L779) |
| Find/create conversation | `start_conversation` — commits | [`conversations/service.py:1749`](../../API/src/app/core/conversations/service.py#L1749) |
| Email one-off send | `send_email` (exactly one of `account_id` / `smtp_sender_id`; opt-out 451; reputation gates; message + activity); render with lead context `templates.render.build_context` + `render_email_template` | [`conversations/adapters/email.py:270`](../../API/src/app/core/conversations/adapters/email.py#L270), [`templates/render.py:38-175`](../../API/src/app/core/templates/render.py#L38), [`email_sequences/scheduler.py:239`](../../API/src/app/core/email_sequences/scheduler.py#L239) |
| Org default sender | `resolve_org_sender` returns a backend object, not an id | [`shared/email/org_sender.py:212`](../../API/src/app/shared/email/org_sender.py#L212) |
| Opt-out checks (3 copies) | `automation/send_guard.check_dpdp_suppression`, `campaigns/send_guard.evaluate_contact`, `workflows/compliance._check_opt_out` | [`automation/send_guard.py`](../../API/src/app/core/automation/send_guard.py) |
| Quiet hours | `tbl_org_settings` quiet window + `transactional_bypass_quiet_hours`; applied by workflows only | [`settings/models.py:131-157`](../../API/src/app/core/settings/models.py#L131), [`workflows/compliance.py:201-254`](../../API/src/app/core/workflows/compliance.py#L201) |
| Template category | `marketing / transactional / service` | [`templates/models.py:86`](../../API/src/app/core/templates/models.py#L86) |
| Inbound events | `whatsapp.message_received`, `email.message_received` | [`events/event_catalog.py`](../../API/src/app/core/events/event_catalog.py) |
| Lead timeline | `tbl_activities` `entity_type='lead'`; FE previews `payload.text` | [`activities/service.py:142`](../../API/src/app/core/activities/service.py#L142) |
| Sweep pattern | claim `FOR UPDATE SKIP LOCKED`, commit, per-row session + `set_context(RequestContext(org_id))`; DB hook sets `app.org_id` per transaction from the context | [`workflows/service.py:2124-2438`](../../API/src/app/core/workflows/service.py#L2124), [`shared/db/__init__.py:33`](../../API/src/app/shared/db/__init__.py#L33) |
| Lapsed subscription | `entitlements.load_for_org(...).is_read_only` | [`subscriptions/entitlements.py:115`](../../API/src/app/core/subscriptions/entitlements.py#L115) |
| Permissions | manual template send = `conversations.write` (Employee has it); `templates.read` (Employee has it) | [`conversations/router.py:678`](../../API/src/app/core/conversations/router.py#L678) |

## What this track does

**Data — `core/leads/auto_send/` sub-module owns it** (models, schemas, data_access, service), table
`tbl_follow_up_auto_sends`: `id`, `org_id` (RLS), `task_id` (unique, FK `tbl_tasks` ON DELETE
CASCADE), `lead_id` (FK `tbl_leads` ON DELETE CASCADE), `template_id` (FK `tbl_message_templates`
ON DELETE SET NULL), `template_name` (snapshot), `channel`, `recipient` (normalised phone/email
snapshot), `status` (`scheduled | claimed | sending | sent | failed | skipped | cancelled`),
`reason` (fixed code only), `claim_token`, `claimed_at`, `attempts`, `not_before`, `message_id`,
`sent_at`, `created_by_id`, `cancelled_by_id`, `cancelled_at`, `created_at`, `updated_at`.
Send time = the task's live `due_at`. Every status change is compare-and-set
(`UPDATE … WHERE status = :expected [AND claim_token = :t]`).

**Shared single-contact send — `conversations/template_send_service.py :: send_template_to_contact`.**
Runs every check **before** creating a conversation: suppression via
`check_dpdp_suppression`, block list, template channel/approval/active, recipient present.
WhatsApp → `start_conversation` + `send_template_message` (gets **typed exceptions** instead of
string `ValueError`s; inbox router maps them). Email → lead-context render + `send_email` from the
**assignee's connected mailbox, else the org default** (`resolve_org_sender` extended to return ids).
Message stamped `payload.author='auto_follow_up'` + `auto_send_id`; sender and conversation owner =
the task assignee. Every lookup filters `org_id` explicitly. Returns
`sent(message_id) | skipped(code) | failed(code) | retry(code)`.

**Scheduling (log-update `next_follow_up.auto_send_template_id`, `replace_existing_auto_send`).**
In the same transaction as the task insert, server checks: `conversations.write`; type is
`whatsapp`/`email`; template in org, channel matches, published, active, (WA) approved; contact has
the address, not suppressed, not anonymised; a sender/number exists; lead not being closed in this
save; `due_at` not in the past (5-min grace) and ≤ 90 days ahead; marketing templates not inside the
org's quiet hours (unless the org bypass applies to the category); per-user cap 100 scheduled per
day; **one pending auto-send per person** (contact row locked, checked across all the contact's
leads) — the existing one is replaced only with `replace_existing_auto_send=true`. Writes a
"scheduled" lead activity + audit. `GET /leads/{id}/auto-send` returns the person's pending one so
the modal can show it before saving.

**Lifecycle.** `POST /leads/auto-sends/{id}/cancel` (`conversations.write` + lead visibility; 409
while `sending`), writes activity, notifies creator and assignee. Reschedule into the past on a task
with a pending auto-send → 422 `auto_send_past_due` (tasks service calls one leads function).
Displayed status is derived from the task as well as the row, and the sweep's housekeeping cancels
`scheduled` rows whose task is no longer open, has no `due_at`, or whose `followup_type` no longer
matches — covering the raw groom and any other writer. Reopening a task does not revive a cancelled
auto-send.

**Sweep (Celery, every 60 s, thin entry in `leads/auto_send/tasks.py`; logic in the service).**
1. Housekeeping (above).
2. Claim fairly: ≤ 25 due rows per org per round (`FOR UPDATE SKIP LOCKED`), set `claimed` +
   token; repeat rounds until none left or a 45 s budget.
3. Per row: fresh session, `set_context(RequestContext(org_id))`; re-check (task open, `due_at ≤ now`,
   type matches, lead exists and not won/lost, contact not anonymised, recipient unchanged, assignee
   active with `conversations.write`, org not read-only, not > 6 h late, quiet hours unchanged);
   CAS `claimed → sending`; send with provider timeout; CAS to outcome.
4. On `sent`: mark the task **done** through the tasks service, lead activity "Auto follow-up sent".
   On `skipped` / `failed`: lead activity + bell to the assignee. Retry only on a definite 429
   (`not_before` + 5 min, max 3). Timeouts and unknown errors are not retried.
5. Reaper: `claimed` > 5 min → back to `scheduled` (never attempted); `sending` > 15 min → `sent`
   if a message with this `auto_send_id` exists, else `failed / interrupted` ("may have been sent").

**Reply auto-cancel.** A subscriber on `whatsapp.message_received` / `email.message_received`
cancels the contact's `scheduled` / `claimed` rows with `lead_replied`, writes activity, notifies
the assignee.

**Due-time reminders.** New `tbl_tasks.due_reminder_sent_at`; a tasks sweep (60 s) sends a bell
"Follow-up due: <lead/contact>" to the assignee for open follow-ups (`followup_type` set) due within
the last hour and not yet reminded, skipping tasks with a pending auto-send. Rescheduling clears
the marker. New notification type registered in `notifications/event_catalog.py`.

**Frontend.** Update Status modal: "Auto-send template (optional)" searchable `crm-mobile-select`
for WhatsApp/Email (only with `conversations.write`), safe preview (WhatsApp text; email in a
sandboxed iframe from the existing preview endpoint), "Will send Fri 28 Nov, 15:53" line,
quiet-hours / opted-out / no-sender warnings, and a banner showing the person's pending auto-send
with **Replace**. Badges ("Auto-message 15:53 · <template>", "Sent · Delivered/Read", "Not sent:
<reason>", "Cancelled") + Cancel on the lead follow-ups panel, dashboard widget and Tasks page.

## What this track does NOT do

- No automatic calls. No general "scheduled message" feature for the inbox (Decision 6).
- No per-follow-up variable overrides; WhatsApp vars from contact + org, email from contact + lead + org.
- No WhatsApp number picker in the modal (lead's conversation number, else org default).
- No editing a scheduled auto-send — cancel or Replace.
- No `task.due` workflow trigger or bus event (no consumer yet).
- Does not fix workflow sends skipping the block list / email gates (follow-up: move them onto `send_template_to_contact`).
- No template version pinning — the template as published at send time is sent.

## Decisions

1. **Separate table owned by `core/leads/auto_send/`**, not columns on `tbl_tasks` and not in
   `core/tasks/` — it is lead-specific and depends on conversations/templates; the tasks module gets
   one call for the reschedule guard.
2. **Send time = live `due_at`.**
3. **One pending auto-send per person** (not per lead); a person with two leads gets one message.
4. **At-most-once.** Unknown outcome → `failed / interrupted`, never resent; only definite 429 retries.
5. **Compare-and-set status + claim token** so cancel, reschedule and reaper never race the sender.
6. **Disagreed with reviewer:** no general scheduled-message primitive in conversations now
   (CLAUDE.md: no abstractions for future flexibility). The send itself is shared.
7. **Sender = assignee** (their mailbox if connected), attribution `payload.author='auto_follow_up'`.
   If the assignee is inactive or lacks `conversations.write` at send time → skipped, notify lead owner.
8. **Quiet hours follow the org's existing settings by template category**, checked when scheduling
   (modal warns) and again at send time (skipped if the window changed).
9. **Skip when the lead is won/lost, the org is read-only, the recipient changed, or > 6 h late.**
10. **Abuse bounds:** 90-day horizon, 100 scheduled per user per day, per-org fair claiming.
    **Disagreed:** no plan-tier caps (no product basis).
11. **Benchmarks — unsourced.** HubSpot sequences (scheduled email steps, unenrol on reply, task
    reminders), Zoho "schedule email" + cadences, Pipedrive scheduled email + activity reminders,
    Wati / Interakt scheduled WhatsApp templates. Matching: stop on reply, rep reminders, rep's
    mailbox. Deliberate difference: one-step send, not multi-step sequences.

## Cases

- A schedules for lead L; B opens Update Status on L → banner shows A's message; B may Replace (cancels A's, notifies A) or keep it.
- Two concurrent schedules for the same person → contact row lock serialises; second sees the first.
- Same person on two leads → one pending auto-send total.
- Task completed / missed / groomed / deleted / type changed / due cleared before due → not sent (housekeeping or cascade).
- Task rescheduled later → sends later. Into the past → 422 `auto_send_past_due`.
- Reschedule or cancel while `claimed` → send-time CAS fails; not sent. Cancel while `sending` → 409.
- Lead deleted → cascade. Contact merged → lead points at survivor; recipient compared to snapshot; if changed → skipped `recipient_changed`.
- Lead replies on WhatsApp/email before due → cancelled `lead_replied`; assignee notified.
- Lead won/lost, contact anonymised/opted out, template unavailable, org read-only → skipped with code; activity + bell.
- No WhatsApp connection / email sender at due time → failed with code; notified.
- Meta 429 → retried ×3 at 5-min gaps. Timeout → `failed / interrupted`.
- Worker dies after claim, before attempt → reaper returns row to `scheduled`. Dies mid-send → `sent` if message row exists, else `interrupted`.
- Beat down 8 h → `too_late`; notified. Reminders older than 1 h are not sent.
- Org X has 80k rows due → other orgs still get ≤ 25 per round each.
- Two orgs in one round → each row uses its own org's number, sender and variables (tested).
- Assignee deactivated → skipped `sender_unavailable`, lead owner notified. Offboarding reassigns tasks → new assignee sends.
- User scripts log-update over thousands of leads → 100/day cap.
- Template from another org → 422 without revealing existence. Extra fields → 422 (`extra="forbid"` incl. nested).
- Email template HTML in preview → sandboxed iframe, no script execution.
- Successful send auto-completes the task → `task.completed` fires as for a manual completion.
- Deploy day: thousands of old overdue open tasks → no reminder flood (1-hour window).

## Tests (named before code)

- **Step 1:** migration up/down, `tbl_` pin-test, RLS policy, cascades from task and lead.
- **Step 2:** sends approved WA template, writes message with `auto_send_id` · suppressed / blocked / unapproved → `skipped` with no conversation created · 429 → `retry` · email renders lead vars, uses assignee mailbox, falls back to org default · two orgs never cross numbers/senders · inbox route still maps errors to the same HTTP codes.
- **Step 3:** schedule creates task + auto-send in one commit · each rejection code (perm, channel, template, recipient, suppression, sender, past, > 90 d, quiet hours, cap, one-per-person) · Replace cancels the old row · `GET /leads/{id}/auto-send`.
- **Step 4:** cancel works, 409 while sending, 404 cross-org · reschedule into past → 422 · housekeeping cancels rows of closed/retyped/undated tasks · summaries on task list, dashboard, panel in one query.
- **Step 5:** one send under two concurrent sweeps · fair claim across orgs · CAS loses to cancel · auto-completes task · too_late / lead_closed / recipient_changed / sender_unavailable · 429 retry then fail · reaper both branches · org isolation.
- **Step 6:** inbound WhatsApp/email cancels pending row with `lead_replied` and notifies.
- **Step 7:** reminder once per due time, reset on reschedule, skipped with pending auto-send, no reminder for > 1 h old.
- **Step 8:** modal picker visibility, warnings, banner + Replace, preview sandbox.
- **Step 9:** badges + Cancel on panel, dashboard, Tasks page.

## Steps

| # | Step | Layer |
|---|---|---|
| 1 | `core/leads/auto_send/` model + migration + DAL | backend |
| 2 | `send_template_to_contact` + typed exceptions + sender resolution | backend |
| 3 | Scheduling in log-update + `GET /leads/{id}/auto-send` | backend |
| 4 | Cancel, reschedule guard, housekeeping, summaries | backend |
| 5 | Sweep: claim, send, CAS, retry, reaper, auto-complete | backend |
| 6 | Reply auto-cancel subscriber | backend |
| 7 | Due-time reminders (`due_reminder_sent_at`) | backend |
| 8 | Update Status modal UI | frontend |
| 9 | Badges + Cancel on panel / dashboard / Tasks page | frontend |
| 10 | Own send time (`send_at`) — send at the follow-up time or a picked time | backend + frontend |
| 11 | Preview filled with the lead's real details | backend + frontend |

Ships after [`contact-tags-for-campaigns`](../contact-tags-for-campaigns/README.md) (both edit
log-update and the Update Status modal). Migration numbers follow that track's `0244`.
