# Step 8 — Lead card + WhatsApp inbox editors; Update Status tags field

## Goal

Staff tag the person from the lead page, the Update Status popup and the WhatsApp inbox.

## Scope

1. `leads/lead-detail.page.{ts,html}` — contact card gets `app-contact-tags-editor` labelled
   "Contact tags · shared across this person's leads" (`canEdit = contacts.write`).
2. `leads/update-status-modal.component.{ts,html}` + `leads-api.service.ts` — "Contact tags" field
   (`crm-tag-input`) prefilled from the contact; submit sends `contact_tags` with only the diff
   against the opened state (omitted when unchanged); on 409 / 422 for tags the form keeps every
   value and shows the error under the field; `saved` emits the resulting tags so the lead card
   refreshes.
3. `conversations/chat-details-rail.component.{ts,html}` — "Contact tags" section with
   `app-contact-tags-editor` for the conversation's contact (separate from conversation tags).

## Tests

Lead card add/remove uses the delta endpoint; read-only without `contacts.write` · Update Status
sends only the diff, omits it when unchanged, keeps the form on error · inbox rail edits the
contact's tags and leaves conversation tags untouched.
