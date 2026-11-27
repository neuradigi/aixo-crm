# Step 4 — `POST /contacts/bulk-tags`; bulk, chatbot and workflow tagging use the delta service

## Goal

Every automated or bulk tag change goes through `stage_tag_delta` / `publish_tag_delta`, so all of
them respect the cap, never lose a concurrent change, and fire `contact.tag_added` / `removed`.

## Scope

1. `shared/schemas/bulk_actions.py` — `BulkTagDelta {ids: 1..200, add, remove}` (reusing
   `ContactTagDelta` rules) and `BulkTagDeltaResult {updated, skipped_over_limit}`.
2. `contacts/service.py` — `bulk_tag_delta_contacts(...)`: one `stage_tag_delta` over the ids
   (contacts that would exceed 32 on add are reported in `skipped_over_limit`, not failed),
   commit, publish. `bulk_add_tag_contacts` becomes a thin call into it (route still used by the
   frontend until Step 5).
3. `contacts/data_access.py` — delete `bulk_append_tag`.
4. `contacts/router.py` — `POST /contacts/bulk-tags` (`contacts.write`).
5. `chatbots/nodes/add_tag.py` — add and remove both call the delta service.
6. `workflows/actions/tagging.py` — `add_tag` / `remove_tag` call the delta service instead of a
   read-modify-write `update_contact`.
7. Tests: `API/tests/test_contact_bulk_tags.py`, adjust existing chatbot / workflow tagging tests.

## Tests

Bulk add+remove on 3 contacts publishes one event per real change · contact at 32 lands in
`skipped_over_limit` · `bulk-add-tag` still returns `{updated}` · chatbot add/remove publishes
events · workflow `add_tag` concurrent with a manual delta keeps both tags.
