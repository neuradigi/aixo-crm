# Step 2 — Tag-delta service, `POST /contacts/{id}/tags`, tag list search + counts

## Goal

One correct way to add/remove tags on contacts (row-locked, exact events, cap on the resulting
list), exposed for a single contact, plus a tag list endpoint that can search and count.

## Scope

1. `contacts/schemas.py` — `ContactTagDelta {add: list[TagName] ≤ 32, remove: list[TagName] ≤ 32}`,
   `extra="forbid"`, 422 when a tag is in both; `ContactTagsResult {tags: list[str]}`;
   `ContactTagOption {tag, count}`; `ContactTagsResponse.tags: list[ContactTagOption]`.
2. `contacts/data_access.py` — `lock_contacts_for_tag_change(session, *, org_id, contact_ids)`
   (`SELECT … FOR UPDATE`, org-scoped); `set_contact_tags(session, *, contact_id, tags)`;
   `list_distinct_contact_tags` gains `q`, `limit`, counts, excludes anonymised.
3. `contacts/service.py`
   - `stage_tag_delta(session, *, org_id, contact_ids, add, remove) -> list[TagDiff]`: locks rows,
     404 for any missing / other-org id, 409 `contact_anonymised`, computes the result per contact
     from the locked snapshot, 422 `tag_limit` (with current count) when an add would leave > 32
     (remove-only always allowed), writes, does **not** commit.
   - `publish_tag_delta(*, org_id, diffs, actor_user_id)`: `contact.tag_added` / `tag_removed` per
     real change via the existing `_publish_contact_tag_event`, `contacts.updated` audit per contact.
   - `apply_contact_tag_delta(session, *, org_id, contact_id, delta, actor)`: stage → commit →
     publish → return resulting tags.
   - `list_contact_tags(session, *, org_id, q, limit)`.
4. `contacts/router.py` — `POST /contacts/{id}/tags` (`contacts.write`) → `ContactTagsResult`;
   `GET /contacts/tags?q=&limit=` allowed for `contacts.read` **or** `campaigns.write`.
5. Frontend type only: `contacts-api.service.ts` `listTags()` returns `ContactTagOption[]`;
   `contacts-list.page.ts` maps `.tag` (keeps today's UI working).
6. Tests: `API/tests/test_contact_tag_delta.py`.

## Tests

Add + remove in one call · concurrent identical adds → one `contact.tag_added` · concurrent adds at
31 tags → one 200, one 422 · remove-only on a 40-tag contact → 200 · anonymised → 409 · other org's
id → 404 · no `contacts.write` → 403 · response carries the resulting list · `{add:[x],remove:[x]}`
→ 422 · `GET /contacts/tags?q=so` returns `[{tag:"sofa",count:2}]`, ignores anonymised contacts,
allowed with only `campaigns.write`.
