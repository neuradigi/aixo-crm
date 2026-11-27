# Step 5 — Contacts list bulk "Tags…" (add / remove); retire `bulk-add-tag`

## Goal

Staff categorise many contacts at once with the same picker, and can remove a tag in bulk.

## Scope

1. `contacts-list.page.{ts,html}` — bulk action "Add tag" becomes "Tags…": a modal (refreshed modal
   styling) with an Add / Remove segmented choice and `crm-tag-input` (suggestions from
   `listTags(q)`); submits `POST /contacts/bulk-tags`; toast reports updated and over-limit counts.
   The `<datalist>` box is removed.
2. `contacts-api.service.ts` — `bulkTags(ids, {add, remove})`; delete `bulkAddTag`.
3. Backend removal: `POST /contacts/bulk-add-tag` route, `bulk_add_tag_contacts`, `BulkAddTag` /
   `BulkAddTagResult` schemas and their tests.

## Tests

Bulk add then bulk remove on selected rows updates the table · over-limit count shown · no
reference to `bulk-add-tag` remains (grep) · backend tests for the removed route deleted.
