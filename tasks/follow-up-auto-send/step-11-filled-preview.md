# Step 11 — Preview filled with the lead's real details

## Goal

The Update Status picker previews the template exactly as this lead will receive it ("Hello
Ajay…"), not with raw `{{ contact.full_name }}` placeholders.

## Scope

1. `GET /leads/{id}/auto-send/preview?template_id=` (`leads.read` + `conversations.write`,
   visible leads only). Read-only; sends nothing. Sender = the lead's owner, else the caller —
   who the follow-up would be assigned to.
2. `template_send_service.preview_template_for_contact` fills the template the same way the send
   does: WhatsApp from contact + org with Meta's blank fallback ("Customer"), via
   `conversations.service.named_variable_data` (extracted from `send_template_message`, which now
   calls it); email from the full lead context via `_email_context` (extracted from `_send_email`).
   An email the send could not fill returns a `problem`.
3. Fix found while building the preview: `render_email_template` rendered only `body_text`, so a
   designed email template went out as plain text. Its HTML part now comes from the template's own
   `body_html` when set — the choice campaigns already make.
4. Picker: loads the filled preview per template (cached), "Loading preview…", caption
   "Preview — what <name> will receive", amber note for a `problem`, falls back to the raw
   template if the preview can't load.

## Tests

WhatsApp fills contact + org with the blank fallback · email fills subject, text and design ·
text-only email has no HTML preview · an unfillable email reports a problem · the real email send
uses the template's design · `preview_auto_send` passes the lead's contact, lead and sender and
404s for a template it can't send · picker requests the preview and shows the filled text.
