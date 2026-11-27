# Contact tags for campaigns — pick, include/exclude, tag from anywhere

Client request (2026-11-27): staff categorise leads with tags so a campaign or WhatsApp template
can go to one category of people. Gaps today:

1. The campaign modal's **Contact tag** box is free text — you must type the exact tag name.
2. A campaign can target **one tag only** and cannot exclude a tag.
3. **Lead screens, the WhatsApp inbox and the contact page have no quick tag editor.**
4. Tags change through four code paths with different rules; bulk and chatbot tagging fire no
   `contact.tag_added` events, so workflows never see them.

Tags stay where they are (`tbl_contacts.tags`, one list per person). This track makes them
pickable, include/exclude-able in campaigns, editable from every screen staff work in, and
changed through one service path. No new tables.

> **Revised 2026-11-27** after the Part C reviewer gate (Attacker · Architect · Absence). Owner
> accepted every safety fix and chose all four extras (exclude tags, inbox editor, bulk add/remove,
> contact-page editor). Disagreements recorded under Decisions.

## What exists today

| Concept | Shape | Cite |
|---|---|---|
| Tag storage | `tbl_contacts.tags varchar(64)[]`, GIN `ix_contacts_tags_gin`, case-sensitive | [`contacts/models.py:131`](../../API/src/app/core/contacts/models.py#L131) |
| Tag rules (3 copies) | ≤ 32 tags, ≤ 64 chars. Create drops > 64 silently; update lets > 64 reach the DB and 500; bulk skips at 32 silently | [`contacts/schemas.py:31-71`](../../API/src/app/core/contacts/schemas.py#L31), [`contacts/service.py:581`](../../API/src/app/core/contacts/service.py#L581), [`shared/schemas/bulk_actions.py:62`](../../API/src/app/shared/schemas/bulk_actions.py#L62) |
| Tag write paths | `PATCH /contacts/{id}` (full replace, events); `bulk_add_tag_contacts` → `bulk_append_tag` (no events, no audit); workflow `tagging.add/remove` (read-modify-write via `update_contact`); chatbot `add_tag` (bulk helper for add, direct assignment for remove, no events) | [`contacts/service.py:596-778,1401`](../../API/src/app/core/contacts/service.py#L596), [`contacts/data_access.py:442`](../../API/src/app/core/contacts/data_access.py#L442), [`workflows/actions/tagging.py:105`](../../API/src/app/core/workflows/actions/tagging.py#L105), [`chatbots/nodes/add_tag.py:65`](../../API/src/app/core/chatbots/nodes/add_tag.py#L65) |
| Org tag list | `GET /contacts/tags` → distinct, alphabetical, cap 500, no search, no counts, `contacts.read` | [`contacts/router.py:236`](../../API/src/app/core/contacts/router.py#L236), [`contacts/data_access.py:338`](../../API/src/app/core/contacts/data_access.py#L338) |
| Contact filter (3 copies) | contacts list `_build_filters` (`?tag=a&tag=b`, OR); campaigns `list_contact_ids_for_audience` (single `tag`); groups `_build_contact_filter_predicates` | [`contacts/data_access.py:164-264`](../../API/src/app/core/contacts/data_access.py#L164), [`campaigns/data_access.py:189-267`](../../API/src/app/core/campaigns/data_access.py#L189), [`contacts/groups/data_access.py:24`](../../API/src/app/core/contacts/groups/data_access.py#L24) |
| Campaign audience | `AudienceFilter.tag: str \| None`, unknown keys silently ignored; JSONB `tbl_campaigns.audience_filter`, re-validated at readiness and enqueue (resolved at send time) | [`campaigns/schemas.py:16-74`](../../API/src/app/core/campaigns/schemas.py#L16), [`campaigns/service.py:862-911`](../../API/src/app/core/campaigns/service.py#L862) |
| Campaign modal | free-text `audience_tag`; preview calls `GET /contacts?tag=`; create-only (never edits an existing audience) | [`create-campaign-modal.component.html:226`](../../APP/src/app/features/user/core/campaigns/create-campaign-modal.component.html#L226) |
| Chip-picker pattern | `crm-mobile-select [pickToAdd] [searchable]` + parent-drawn chips | [`create-campaign-modal.component.html:242-335`](../../APP/src/app/features/user/core/campaigns/create-campaign-modal.component.html#L242), [`shared/forms/mobile-select.component.ts`](../../APP/src/app/features/user/core/shared/forms/mobile-select.component.ts) |
| Tag editors in UI | contact form: comma text box; contact page: read-only chips; contacts list bulk: free-text + `<datalist>`; lead card / inbox rail: none | [`contact-form-modal.component.html:206`](../../APP/src/app/features/user/core/contacts/contact-form-modal.component.html#L206), [`contact-detail.page.html:114`](../../APP/src/app/features/user/core/contacts/contact-detail.page.html#L114), [`contacts-list.page.html:671-727`](../../APP/src/app/features/user/core/contacts/contacts-list.page.html#L671), [`lead-detail.page.html:277`](../../APP/src/app/features/user/core/leads/lead-detail.page.html#L277) |
| Update Status contact edits | `contact_basics` (name/phone/email, `extra="forbid"`); `contacts.write`; 422 `contact_shared` if > 1 lead; fields set directly → no contact events | [`leads/schemas.py:142-245`](../../API/src/app/core/leads/schemas.py#L142), [`leads/router.py:506-544`](../../API/src/app/core/leads/router.py#L506), [`leads/service.py:1897`](../../API/src/app/core/leads/service.py#L1897) |
| Deploy | `run.sh upgrade` runs `alembic upgrade head` as its own container, separate from `up --build` | `API/run.sh` |

## What this track does

**Backend**
- **One tag type.** `TagName` in `contacts/schemas.py`: NFC-normalised, trimmed, 1–64 chars,
  rejects control and bidi-override characters. Invalid → **422, never silently dropped**. Used by
  create, PATCH, delta, bulk, audience and log-update. `ContactTagDelta {add: list[TagName] ≤ 32,
  remove: list[TagName] ≤ 32}`, `extra="forbid"`, 422 if a tag is in both lists.
- **One tag write path.** `contacts.service.stage_tag_delta(session, *, org_id, contact_ids, add,
  remove)` locks the rows (`SELECT … FOR UPDATE`, org-scoped, excludes anonymised), computes the
  diff from the locked snapshot, enforces the 32 cap on the **resulting** list (remove-only always
  allowed; nothing applied on 422), writes, and returns the per-contact diff without committing.
  `contacts.service.publish_tag_delta(org_id, diffs, actor)` publishes `contact.tag_added` /
  `contact.tag_removed` once per real change and writes the `contacts.updated` audit — called by
  every caller after its commit. Callers: new `POST /contacts/{id}/tags`, new
  `POST /contacts/bulk-tags {ids, add, remove}` (replaces `bulk-add-tag`), log-update, workflow
  `tagging.add_tag/remove_tag`, chatbot `add_tag`. `bulk_append_tag` is deleted.
- **Tag list endpoint grows up.** `GET /contacts/tags?q=&limit=` → `[{tag, count}]` from
  non-anonymised contacts, server-side search; allowed with `contacts.read` **or** `campaigns.write`.
- **One contact filter.** The contacts DAL filter builder becomes public and the campaigns DAL calls
  it, so the campaign preview (contacts list) and dispatch resolve the same set. Adds
  `tags` (any of, `&&`) and `exclude_tags` (none of, `NOT &&`). Contacts list gains `exclude_tag`.
- **Audience format change in two releases** (Decision 3):
  - *Release 1 (Step 1):* `AudienceFilter` reads `tags`, `exclude_tags` **and** legacy `tag`
    (normalised to `tags=[tag]`), `extra="forbid"` on it and nested models, empty lists rejected.
    Frontend still writes `tag`. Safe to run next to old code: nothing writes the new shape yet.
  - *Release 2 (Step 6, only after Release 1 is live in prod):* data migration `0244` rewrites
    stored `tag` → `tags`, legacy `tag` dropped from the schema, frontend writes `tags` /
    `exclude_tags`. Rolling back to Release 1 is safe — it reads `tags`.
- **Log-update takes `contact_tags: ContactTagDelta | None`.** Contact resolved from the lead on the
  server; `contacts.write` required only when the delta is non-empty; not blocked by
  `contact_shared`; staged in the modal's single transaction; published after commit.
- **PATCH /contacts** validates tags with `TagName` (fixes the > 64 → 500).

**Frontend**
- **`crm-tag-input`** (`shared/forms/tag-input.component.ts`), vocabulary-agnostic: inputs
  `[suggestions]` (`{value, count?}`), `[maxTags]`, `[maxLength]`, `[snapCase]`; output `(search)`
  for server-side lookup; `ControlValueAccessor` of `string[]`. Chips + type-ahead, Enter/comma adds,
  case-insensitive **snap to existing spelling**, Backspace removes last, uncommitted text is
  committed on blur. Text only via interpolation — no `innerHTML`. Same tokens and panel styling as
  `crm-mobile-select`. Loads suggestions on focus.
- **Campaign modal:** two chip-pickers, "Has any of these tags" and "Doesn't have any of these
  tags", searchable, with contact counts; preview sends `tag` / `exclude_tag`.
- **Contact form modal:** `crm-tag-input`; sends `tags` only if the user changed them.
- **Contact page, lead page contact card, WhatsApp inbox details rail:** inline "Contact tags"
  editor (one shared wrapper component) saving through the delta endpoint; shows the server's
  resulting list; optimistic chip reverts on error; read-only without `contacts.write`. Lead card
  label: "Contact tags · shared across this person's leads".
- **Update Status modal:** "Contact tags" field; sends only the diff against the opened state.
- **Contacts list bulk action:** "Tags…" modal with Add / Remove using `crm-tag-input`.

## What this track does NOT do

- **No lead-level tags.** A tag describes the person (Decision 1).
- **No AND ("has all of") rule.** Any-of include + none-of exclude only.
- **No tag management screen** (rename / merge / colours / delete everywhere). Follow-up track — it
  must also rewrite tags stored in `tbl_campaigns.audience_filter`.
- **No merge of conversation tags (`tbl_conversation_tags`) and contact tags.** The inbox rail gets a
  separate "Contact tags" editor; conversation tags still cannot target campaigns. Follow-up decides.
- **No saved custom-filter audiences** (HubSpot active lists / Mailchimp saved segments, unsourced).
- **No change to dynamic contact groups' `GroupFilter`** (UI creates static groups only).
- **No case-folding of existing tags**, no tag filter/column on the leads list, no catalog
  chip-input migration onto `crm-tag-input`, `AudienceFilter.source` unchanged.
- **Merge keeps its existing union**; a merged contact may exceed 32 — only removes are then allowed.

## Decisions

1. **Tags stay on the contact.** Campaign dispatch, groups, workflows and chatbots all read
   `tbl_contacts.tags`. Consequence: a product tag (`sofa`) outlives the sofa lead; orgs that want
   it removed on Won/Lost use a workflow (`lead won` → `tagging.remove_tag`).
2. **Tags over the existing multiselect custom field**: campaigns already target tags; custom
   fields are not an audience filter today.
3. **Two-release expand/contract for the audience shape.** Old code silently ignores unknown keys,
   so any old reader meeting `tags` would send to **everyone**. Release 1 makes every reader
   understand `tags` before anything writes it. Step 6 must not deploy until Step 1 is live.
4. **Empty never means everyone.** `tags: []` / `exclude_tags: []` are 422; the DAL branches on
   `is not None`; a stored `tag: ""` migrates to an explicit readiness error, not to "no filter".
5. **Row lock + diff from the locked snapshot**, not a bare `UPDATE … RETURNING`, so the cap check
   and "newly added" event set are exact under concurrency.
6. **Tag edits from Update Status bypass `contact_shared`** (that guard protects identity fields).
7. **Snap-to-existing is client-side**; storage stays case-sensitive.
8. **Disagreed with reviewers:** no per-user rate limit on tag edits (PATCH already allows the same;
   32-item request cap + exact events suffice); no DB `CHECK (cardinality ≤ 32)` (merge can
   legitimately exceed it); CSV formula escaping on export is an existing contacts-export concern,
   not this track; no cache for the tag list (server-side `q` + limit + load-on-focus).
9. **Benchmarks — unsourced (no `PRODUCT_BRIEF.md`).** Zoho: free-text tags + tag manager + view
   filters. Pipedrive: fixed admin labels. HubSpot: lists with AND/OR. Mailchimp / ActiveCampaign:
   "is tagged / is not tagged". Wati / Interakt / Respond.io: contact tags edited from the inbox
   panel. Deliberate differences: no tag manager yet; no AND rule; no saved segments.

## Cases

- Release 1 live, old bundle still in a browser → it writes `tag`; Release 1 reads it as `tags=[tag]`.
- Release 2 migration runs while a Release 1 worker is still up → that worker reads `tags`; same audience.
- Production rolled back from Release 2 to Release 1 → reads migrated rows correctly.
- Stored audience row with an unknown key → readiness and enqueue fail with a validation error; campaign does not send; never "everyone".
- Stored `tag: ""` → migrated to a value readiness rejects; operator fixes the campaign.
- `tags: ["   "]` or a 65-char tag → 422, not dropped.
- A and B add `video` to the same contact at once → one row change, one `contact.tag_added`.
- Contact has 31 tags; A adds `x`, B adds `y` at once → one succeeds, the other gets 422 `tag_limit`.
- Contact has 40 tags after a merge → remove-only deltas succeed; adds return 422 until ≤ 32.
- `{add:["x"], remove:["x"]}` → 422.
- A edits the contact form (no tag change) while B adds `c` from the lead page → A's save omits `tags`; `c` survives; no false `tag_removed`.
- A edits tags in the contact form while B uses the delta endpoint → last write wins on the full list (form behaviour).
- Lead page open on contact X; B merges X away → A's tag request returns 404; page reloads the lead's current contact.
- Contact anonymised concurrently with a tag add → row lock serialises; add on anonymised → 409 `contact_anonymised`.
- Update Status sends `contact_tags: {add:[], remove:[]}` from a user without `contacts.write` → treated as absent; no 403.
- Update Status tag delta fails (422/409) → whole save rejected; modal keeps every typed value and shows the error on the tags field.
- Contact on several leads → tag change from any lead shows on all; `contact_basics` still guarded by `contact_shared`.
- Campaign builder with `campaigns.write` but not `contacts.read` → tag picker still loads.
- Org with > 500 tags → server-side `q` search finds any tag; snap uses search results.
- Tag containing `<img onerror>` → rendered as text everywhere.
- Bulk tag 200 contacts → one statement set, events per real change, audit per contact.
- Chatbot / workflow tag changes now fire events (previously silent for bulk/chatbot) — orgs with `contact.tag_added` workflows will see them run for chatbot tagging. Recorded behaviour change.
- Tag added after a campaign was scheduled → the contact receives it (audience resolves at send time — existing behaviour).

## Tests (named before code)

- **Step 1:** `TagName` rejects control/bidi chars and 65-char strings · `AudienceFilter` accepts `tag`, `tags`, `exclude_tags`, rejects unknown keys and empty lists · audience `tags=[a,b]` + `exclude_tags=[c]` resolves contacts with a or b and not c · campaign preview query and dispatch query return the same contact ids for the same filter · PATCH contact with a 65-char tag → 422.
- **Step 2:** delta adds/removes in one call · concurrent identical adds → one event · concurrent adds at 31 → one 422 · remove-only on a 40-tag contact succeeds · anonymised → 409 · cross-org id → 404 · no `contacts.write` → 403 · response returns the resulting list · `GET /contacts/tags?q=vi` returns matching tags with counts, excludes anonymised contacts, allowed for `campaigns.write`.
- **Step 3:** `crm-tag-input` snaps `hot` → `Hot`, commits text on blur, refuses 33rd / 65-char tag, renders markup as text · contact form omits `tags` when untouched · contact page inline add calls the delta endpoint and shows the returned list; reverts chip on error.
- **Step 4:** `bulk-tags` add+remove on 3 contacts publishes events per real change · `bulk-add-tag` route still works through the new path · chatbot add/remove and workflow add/remove publish events and never lose a concurrent change.
- **Step 5:** contacts list bulk "Tags…" adds and removes via `bulk-tags`; old route and schema removed.
- **Step 6:** migration: `{"tag":"vip"}` → `{"tags":["vip"]}`, `{"tag":""}` → readiness-rejected value, rows without `tag` untouched, downgrade restores single `tag` from the first element · schema rejects legacy `tag` · modal sends `tags` / `exclude_tags`, preview sends `tag` / `exclude_tag`.
- **Step 7:** log-update `contact_tags` applies in the same commit as the remark · empty delta without `contacts.write` → 200 · non-empty without it → 403, nothing written · shared contact accepts tags while `contact_basics` → `contact_shared` · events only after commit · contact derived from the lead, not the body.
- **Step 8:** lead card, inbox rail editors use the delta endpoint; read-only without `contacts.write` · Update Status sends only the diff and keeps form values on error.

## Steps

| # | Step | Layer | Ship note |
|---|---|---|---|
| 1 | `TagName`, `AudienceFilter` reads `tag`/`tags`/`exclude_tags` + forbid, shared contact filter builder | backend | **Release 1 — deploy to prod before Step 6** |
| 2 | Tag-delta service + `POST /contacts/{id}/tags` + tag list `q`/counts/permissions | backend | |
| 3 | `crm-tag-input` + inline contact-tags editor; contact form + contact page use them | frontend | |
| 4 | `POST /contacts/bulk-tags`; bulk, chatbot, workflow tagging routed through the delta service | backend | |
| 5 | Contacts list bulk "Tags…" add/remove; remove old `bulk-add-tag` | frontend + backend removal | |
| 6 | Migration `0244`, drop legacy `tag`; campaign modal include/exclude pickers | backend + frontend | **Release 2** |
| 7 | Log-update `contact_tags` | backend | |
| 8 | Lead card + inbox rail editors; Update Status tags field | frontend | |

Overlap with [`follow-up-auto-send`](../follow-up-auto-send/README.md): both edit
`log_update_for_lead`, `LogUpdateRequest` and the Update Status modal. Ship this track first.
