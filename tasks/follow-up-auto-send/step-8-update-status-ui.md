# Step 8 — Update Status modal: auto-send template picker

## Goal

Staff pick an optional template when the follow-up is WhatsApp or Email, see what will be sent and
when, and are warned before saving about anything that would stop it.

## Scope

1. `leads-api.service.ts` — `NextFollowUpSpec.auto_send_template_id`,
   `replace_existing_auto_send`; `getPendingAutoSend(leadId)`.
2. `update-status-modal.component.{ts,html}`:
   - "Auto-send template (optional)" searchable `crm-mobile-select`, shown for WhatsApp / Email
     with `conversations.write`; options from `/templates` (WhatsApp: published + approved +
     active; Email: published + active), blank by default.
   - Preview: WhatsApp body text; email via the existing preview endpoint in a sandboxed
     `<iframe sandbox>` (no scripts, no same-origin).
   - "Will send Fri 28 Nov, 15:53" line; warnings: no phone / email, opted out, inside quiet
     hours for a marketing template.
   - Banner when the person already has a pending auto-send, with **Replace** / **Keep**.
   - 409 `auto_send_exists` and other auto-send codes shown under the field; form kept.

## Tests

Picker hidden for Call and without `conversations.write` · only usable templates listed · payload
carries the template id · banner + Replace sets `replace_existing_auto_send` · email preview
renders inside a sandboxed iframe.
