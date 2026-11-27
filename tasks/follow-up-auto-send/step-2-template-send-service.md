# Step 2 — `conversations/template_send_service.py :: send_template_to_contact`

## Goal

One function that sends a saved template to one contact, runs every gate before touching the
provider, and reports a clear outcome instead of raising HTTP errors.

## Scope

1. `conversations/exceptions.py` — `TemplateSendRejected(ValueError)` with a fixed `code`;
   `send_template_message` raises it instead of string `ValueError`s (subclassing `ValueError`
   keeps the inbox route's `ValueError → 400` mapping unchanged); both `send_template_message`
   and `send_email` gain `extra_payload` merged into the message payload.
2. `email/data_access.py` — `find_live_account_for_user`. No `org_sender` change: when no
   mailbox is passed, `send_email` already runs the org send cascade.
3. `conversations/template_send_service.py` — `send_template_to_contact(session, *, org_id,
   contact_id, lead_id, template_id, sender_user_id, auto_send_id) -> SendOutcome`:
   - Checks first (no conversation created when any fails): contact exists in org, not
     anonymised, has the channel address; suppression via `automation.send_guard.check_dpdp_suppression`;
     WhatsApp block list; template in org, channel matches, published, active, (WA) approved.
   - WhatsApp: `start_conversation` → `send_template_message` (sender = `sender_user_id`).
   - Email: `templates.render.build_context` with the lead → `render_email_template` →
     `send_email` from the resolved sender.
   - Message payload stamped `author='auto_follow_up'`, `auto_send_id`.
   - Returns `SendOutcome(kind: sent | skipped | failed | retry, code, message_id)`; Meta 429 →
     `retry`; timeouts / unknown errors → `failed` (never retried).
4. Tests: `API/tests/test_template_send_service.py`.

## Tests

Approved WA template sends and the message row carries `auto_send_id` · opted-out / blocked /
unapproved / inactive / missing phone → `skipped` and no conversation created · 429 → `retry` ·
email renders a lead variable, uses the user's mailbox, falls back to the org default · two orgs
in one process never cross sender or number · inbox template route still returns the same codes.
