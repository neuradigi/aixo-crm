# Step 6 — Cancel on reply

## Goal

When the lead messages us before the follow-up time, the scheduled auto-send is cancelled and the
assignee is told.

## Scope

1. `leads/auto_send/subscribers.py` — events-bus subscriber for `whatsapp.message_received` and
   `email.message_received` (registered the same way `workflows/trigger_handlers.py` subscribes):
   resolves the contact, CAS-cancels its `scheduled` / `claimed` rows with `lead_replied`, writes
   a lead activity, notifies the assignee.
2. Registration import in the leads module descriptor.
3. Tests: `API/tests/test_follow_up_auto_send_reply_cancel.py`.

## Tests

Inbound WhatsApp from the contact cancels its pending row · inbound email does too · a message
from a different contact does not · a row already `sending` is left alone · the assignee is
notified once.
