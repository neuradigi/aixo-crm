# Step 3 — `crm-tag-input` + inline contact-tags editor; contact form and contact page

## Goal

A reusable chip tag input in the app's current design language, and the inline editor built on it,
used first on the contact form modal and the contact detail page.

## Scope

1. `APP/src/app/features/user/core/shared/forms/tag-input.component.ts` — selector `crm-tag-input`,
   `ControlValueAccessor<string[]>`. Inputs `suggestions: {value, count?}[]`, `maxTags = 32`,
   `maxLength = 64`, `snapCase = true`, `placeholder`; output `search(q)`. Chips + type-ahead panel
   styled like `crm-mobile-select` (same tokens, panel, focus ring). Enter / comma adds; typed text
   matching a suggestion case-insensitively becomes that suggestion's spelling; Backspace on empty
   removes the last chip; uncommitted text committed on blur; limits shown inline. Text rendered by
   interpolation only.
2. `APP/.../contacts/contact-tags-editor.component.ts` — selector `app-contact-tags-editor`, inputs
   `contactId`, `tags`, `canEdit`, `label`; loads suggestions on focus via
   `contactsApi.listTags(q)`; each add/remove calls `POST /contacts/{id}/tags`; renders the
   server's returned list; reverts the optimistic chip and shows the error on failure; read-only
   chips when `canEdit` is false. Output `tagsChange`.
3. `contacts-api.service.ts` — `updateTags(id, {add, remove})`, `listTags(q?)`.
4. `contact-form-modal.component.{ts,html}` — `crm-tag-input` replaces the comma box; `tags` sent on
   edit only when changed.
5. `contact-detail.page.{ts,html}` — header chips become `app-contact-tags-editor`
   (`canEdit = contacts.write`).

## Tests

`crm-tag-input`: `hot` → existing `Hot`; blur commits text; 33rd and 65-char tags refused with a
message; `<b>x</b>` tag rendered as text · contact form: untouched tags → payload has no `tags` ·
contact detail: add calls `updateTags` and shows the returned list; error reverts the chip.
