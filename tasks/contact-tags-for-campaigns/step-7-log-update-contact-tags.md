# Step 7 — Log-update accepts `contact_tags`

## Goal

Update Status can change the lead's contact tags in the same atomic save as the remark, stage and
follow-up, with the same events and audit as every other tag change.

## Scope

1. `leads/schemas.py` — `LogUpdateRequest.contact_tags: ContactTagDelta | None`.
2. `leads/router.py` — require `contacts.write` only when `contact_tags` has a non-empty `add` or
   `remove`.
3. `leads/service.py` — `log_update_for_lead`: contact id taken from the locked lead row; call
   `contacts.service.stage_tag_delta` inside the transaction (not subject to `contact_shared`);
   after commit call `contacts.service.publish_tag_delta`; `LogUpdateResponse` gains
   `contact_tags: list[str] | None` (resulting list when tags changed).
4. Tests in `API/tests/test_leads_log_update_tags.py`.

## Tests

Tags applied in the same commit as the remark · empty delta without `contacts.write` → 200 ·
non-empty without it → 403, nothing written · shared contact accepts tags while `contact_basics`
→ 422 `contact_shared` · `tag_limit` rolls back the whole save · events only after commit ·
another org's lead → 404.
