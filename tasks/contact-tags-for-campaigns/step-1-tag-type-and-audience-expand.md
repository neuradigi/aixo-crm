# Step 1 — `TagName` type, `AudienceFilter` reads `tags` / `exclude_tags`, one contact filter

**Release 1 of the two-release audience change. Deploy this step to production before Step 6.**

## Goal

Every reader of a campaign audience understands the new shape (`tags`, `exclude_tags`) before
anything writes it, unknown audience keys fail loudly, and the campaign dispatch filter is the same
code as the contacts-list filter the campaign preview uses.

## Scope

1. `API/src/app/core/contacts/schemas.py`
   - `TagName` (`Annotated[str, AfterValidator]`): NFC-normalise, strip, reject empty, > 64 chars,
     C0/C1 control characters and bidi / zero-width controls (U+200B–U+200F, U+202A–U+202E,
     U+2066–U+2069, U+FEFF). Invalid → validation error (422), never dropped.
   - `ContactCreate.tags` / `ContactUpdate.tags` use `list[TagName]` (≤ 32). `cleaned_tags()` keeps
     its de-duplication but no longer silently drops long tags (validation already rejected them).
2. `API/src/app/core/contacts/data_access.py`
   - `_build_filters` → public `build_contact_filters`; `tags` uses `Contact.tags.overlap(tags)`
     (same any-of semantics, GIN-indexable); new `exclude_tags` → `~Contact.tags.overlap(...)`.
     Branches on `is not None`-and-non-empty exactly as today for every other list.
3. `API/src/app/core/campaigns/schemas.py` — `AudienceFilter`:
   - `model_config = ConfigDict(extra="forbid")`.
   - `tags` / `exclude_tags`: `list[TagName] | None`, 1–20 items when present (empty list → 422).
   - Legacy `tag: TagName | None` still accepted **and stored as sent** (the frontend still writes
     it in this release; rewriting it here would hand pre-Release-1 code a shape it ignores).
   - `tag` together with `tags` → 422. `exclude_tags` counts as a filter field for the
     mixed-mode check. `effective_tags` property = `tags`, else `[tag]`, else `None`.
4. `API/src/app/core/campaigns/data_access.py` — `list_contact_ids_for_audience` takes `tags` /
   `exclude_tags` and builds its predicates with `contacts.data_access.build_contact_filters`
   (deletes the parallel copy).
5. `API/src/app/core/campaigns/service.py` — `resolve_audience` passes `af.effective_tags`,
   `af.exclude_tags`.
6. Tests: `API/tests/test_campaigns_audience_tags.py`, `API/tests/test_contact_tag_validation.py`.

## Out of scope

Frontend (still sends `tag`), contacts list `exclude_tag` query param (Step 6), data migration
(Step 6), tag-delta endpoint (Step 2).

## Tests

- `TagName` rejects a 65-char tag, a tag with U+202E, a tag with `\x07`; NFC-normalises a decomposed `é`.
- `ContactUpdate(tags=[65 chars])` raises → PATCH returns 422 instead of a DB error.
- Audience `{"tags": ["sofa","chair"]}` → contacts with sofa or chair.
- Audience `{"tags": ["sofa"], "exclude_tags": ["vip"]}` → sofa contacts without vip.
- Legacy `{"tag": "sofa"}` → same result as before.
- `{"tag": "a", "tags": ["b"]}`, `{"tags": []}`, `{"exclude_tags": []}`, `{"nope": 1}` → validation error.
- `{"exclude_tags": ["x"], "group_id": …}` → mixed-mode error.
- Same filter through the contacts-list query and `resolve_audience` → same contact ids.

## Pre-deploy check (prod)

Rows that will now fail readiness because of an unknown audience key:

```sql
SELECT id, name, status, audience_filter
FROM tbl_campaigns
WHERE audience_filter - ARRAY['q','source','tag','tags','exclude_tags','lead_status',
      'lead_stage','lead_source','lead_form_id','group_id','contact_ids'] <> '{}'::jsonb;
```
