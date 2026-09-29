---
plan_id: 20260926-video-metadata-enrichment
iteration: iter-2026-09-metadata-audio-layout
iteration_compass: .mstar/iterations/iter-2026-09-metadata-audio-layout/delivery-compass.md
primary_spec: .mstar/iterations/iter-2026-09-metadata-audio-layout/specs/metadata-coverage-contract.md
iteration_refs:
  - .mstar/iterations/iter-2026-09-metadata-audio-layout/specs/metadata-coverage-contract.md
blocked_by: []
qa_gate: mandatory
qa_mode: targeted
execution_mode: sdd
status: registered
gate_decision: pass
gate_decision_reason: Prepare gates specify/clarify/plan satisfied; compass locked 2026-09-26 after the Phase-1 review-and-edit chain
gate_decided_at: 2026-09-26
registered_at: 2026-09-26
planned_at_sha: 9d530cd
agents:
  implementer: fullstack-dev
  task_reviewer: code-reviewer
  plan_qc: qc-specialist
  qa: qa-engineer
---

# Persist the video metadata the archive already receives

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. Steps use
> checkbox (`- [ ]`) syntax for tracking.
>
> **This plan is NOT yet dispatched.** It is registered as a plan of iteration
> `iter-2026-09-metadata-audio-layout`, which is registered and **`locked`** as of 2026-09-26 — the Phase-1
> review-and-edit chain completed (all three seats ran, every marker cleared). Two independent gates hold dispatch: the compass must reach
> `locked`, and the compass `## Blocked By` serial-dispatch rule must lift (the live iteration
> `iter-2026-09-qwen3-asr-closeout` must reach Phase 6, or the operator must release the rule). Registration
> authorises no implementation.
>
> **This is the first plan in the capacity order (compass D13):** if the window fits only one of the
> iteration's two plans, this one takes the slot and `20260926-audio-inventory` gives way.

**Goal:** Persist the video-level metadata the pipeline already receives and then discards, so a reader of an
archived transcript can see what the video *was* — its real title, its uploader's name, its tags, its
category and its cover — instead of a bare `bvid` and a part title that is sometimes the string `哲学课3`.

**What this plan does *not* promise (read before quoting any criterion):**

- **No point-in-time snapshot.** Per compass **D11**, the video facts this plan stores are a **dated
  working index**, refreshed on the next collection: one row per video, and `video_details.observed_at`
  means "the last **successful** collection", not "the collection that first saw this field". A reader must
  not infer from the stored grain that the archive holds what upstream said on a given date. Nothing here is
  a historical record, and the plan may not be described as one.
- **The stamp is not advanced by an empty observation.** Per compass **D15**, a collection carrying none of
  `pic`/`desc`/`tid` leaves the row and its `observed_at` untouched, because the column means *last
  successful* collection. The grain is unchanged — one row per video, refreshed (D11); D15 constrains only
  when the stamp moves.
- **No change to `export`.** Per compass **D12**, `export` keeps redacting `http(s)://` values and dropping
  `*_url` keys, so the stored cover is invisible in every export **by design**. `export.py` is not modified.
- **The uploader name stops being a placeholder; it does not become a profile system.** `display_name` is
  written from the `author` the list response carries. A run whose page had no `author` still falls back to
  `str(mid)`.
- **No credential, and no per-part call.** The tag call stays unsigned, one GET per **video**.

**Architecture:** Four hops, in the order the data actually travels: the gateway normalizers
(`sources/bilibili_api_gateway.py`) read more of the responses they already parse; the DTOs
(`sources/models.py`) carry the new fields; the storage records and `schema.sql` hold them; and the readers
(`list_stored_transcripts` → the writer entry → frontmatter/FTS/manifest) surface them. Every addition is
either **free** (already in a response the pipeline fetches today) or **one extra unsigned GET per video**
(tags only — the one field the operator named).

**Tech Stack:** Python 3.12, SQLite 3 (`sqlite3` stdlib), `bilibili-api-python==17.4.2` (pinned; the tag call
is issued through the package's own `Api` + endpoint descriptor, never a raw `requests` call), pytest.

**Execution:** mstar-sdd

**Main worktree branch**: `main` (recorded 2026-09-26; the control root stays on `main` — never switched).

## Global Constraints

- **Naming discipline.** Any new identifier — column, DTO field, frontmatter key, function, command — is
  chosen with the `naming-analyzer` skill before it lands, and the rejected alternatives are recorded. The
  names this plan proposes are already through that pass (see `## Naming decisions` below); a rename that
  departs from them is a plan change, not an implementation detail.
- **The gateway boundary is not widened.** `sources/bilibili_api_gateway.py` remains the **only** module that
  imports `bilibili_api`. New calls are issued through the imported endpoint descriptors
  (`_TAG_ENDPOINT = VIDEO_API["info"]["tags"]`), and no raw `requests`/`httpx` call may be introduced.
- **Credentials never reach a stored field.** `SESSDATA` stays unserialised, unlogged and unreturned, exactly
  as today. The tag call this plan adds is **unsigned** and must stay that way — do not add a credential to
  it.
- **`DOCUMENTED_METADATA_CALLS` is exact and guarded.** Adding tags means adding its call name to
  `tests/fixtures/fake_bilibili_gateway.py:138-144` **and** to the exact-set pin in
    `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` — measured at `:2418` on this branch; a pre-T1/T2 pointer named `:2272`, so find it by the assertion rather than the number.
  (`assert_only_documented_metadata_calls`, `fake_bilibili_gateway.py:821-827`).
- **Schema evolution policy.** `initialize_schema` (`storage/database.py:154-172`) runs only
  `CREATE ... IF NOT EXISTS`. Therefore: a **new table** is live-additive on an existing database; a **new
  column on an existing table** is silently absent on any existing `archive.db` and its first `INSERT`
  fails. `test_schema_inspection_matches_the_declared_contract` (`:856-942`) asserts **four** per-table maps
  besides membership in `BASE_TABLES` (`:47`) — `EXPECTED_TABLE_COLUMNS` (`:69`), `EXPECTED_FOREIGN_KEYS`
  (`:173`), `EXPECTED_PRIMARY_KEY_INDEXES` (`:205`) and, for a declared index, `EXPECTED_INDEXES` (`:215`),
  while `EXPECTED_UNIQUE_CONSTRAINTS` (`:198`) defaults to `()` — each read as `.get(table, ())`, so a
  missing entry **fails** rather than being skipped. Every schema change updates the relevant maps in the
  same task, or the suite fails. **Measured for this plan's two tables:** the columns, foreign-key and
  primary-key-index entries are required for both; the unique-constraint and declared-index maps need none.
- **The md frontmatter key set is pinned.** `test_write_archive_publishes_the_exact_asr_key_set`
  (`tests/test_archive_md.py:296-333`) asserts the **exact ordered 24-key list** (`assert len(front) == 24`).  *(Pre-revision baseline: Task 2 has since moved this pin to **25** — see the
`## Verification plan` rows and `tests/test_archive_md.py`'s `assert len(front) == 25`.)*
  A new frontmatter key is a deliberate, pinned format revision: update the assertion in the same commit and
  say so in the commit body.
- **`export` redaction is a naming constraint *and* a settled policy (compass D12).** In
  `src/bili_asr/export.py`, `_is_sensitive_key` (`:85-98`) drops any key listed in `SENSITIVE_EXPORT_KEYS`
  (`:37-64`, which names `cover_url` exactly at `:48`), any key ending in one of
  `_SENSITIVE_KEY_SUFFIXES` (`:66-73`), and any key ending in `url` (`:94`); and `_sanitize_value`
  (`:174-177`) replaces every string starting `http://`/`https://` with `[redacted]`. So a cover column must
  not be named `*_url`, **and** its stored value will still be redacted in every export. **That second half
    is the ruling, not an accident:** the cover is store-only by decision (D12), **no `export.py` change is
    owed or permitted to surface the cover** — Task 4 adds no column and never touches the file. Task 5
    separately adds `video_title` to `STANDARD_CSV_COLUMNS` under its own licence (Task 5 `## Files`,
    and the corrected Done criterion at the end of this plan), which is a different change to a
    different column for a different reason.
  A cover that must appear in a shared export is still a new decision with its own trigger.
  See Task 4 (the category/cover slice).
- **Verification scope.** `mstar-harness-core` § 定向执行与验证边界: only the changed behaviour and its
  direct contracts. No local full-suite run without explicit user permission; the full suite is CI's. Each
  task's gate is its own named pytest selector.
- **A sibling plan shares one test file with this one.** `20260926-audio-inventory` (the iteration's second
  plan, D13) runs `tests/test_storage_schema.py` as its own gate and touches the **same four maps** this plan
  extends, for the two tables it does **not** change (D7). The two plans collide on **no schema object** —
  this plan adds `video_tags` + `video_details`; the audio plan adds nothing — but a map read as a whole-file
  invariant would look like drift from either side. Neither plan may "restore" the file, and neither may
  reorder or drop the other's entries. The audio schema tables (`audio_objects`, `part_audio_objects`) and
  their map entries stay exactly as written.
- **Upstream politeness.** The tag call is one GET per **video** (not per part) and must be **cached per
  bvid within a run**. The live probe on 2026-09-26 got an upstream `412` on `/x/space/wbi/arc/search` after
  two successes, so the risk-control surface is real and this plan must not multiply calls per part.

## Naming decisions

Recorded per the project's naming discipline (`naming-analyzer`). These are settled; Task authors use them
verbatim.

| Thing | Chosen | Rejected | Why |
|---|---|---|---|
| Table | `video_tags` | `tags` | `tags` collides with the note/topic/opus tag concept the pinned package also models (`data/api/topic.json`, `opus.json`); the prefix states the owner the FK enforces. |
| Tag columns | `bvid`, `tag_id`, `tag_name`, `tag_type` | `name`, `id`, `type` | Matches upstream's own field names and avoids a bare `id` beside `bvid`. |
| Frontmatter key | `video_title` | redefining `title` | `title` is already the part title and is in the then-pinned 24-key set (25 since Task 2). Redefining it silently changes a published key; a sibling key is additive and honest. |
| `videos` column | `pic` | `cover_url`, `cover` | `cover_url` is an exact match in `SENSITIVE_EXPORT_KEYS` (`export.py:48`); any `*_url` name is dropped by two independent rules — the suffix tuple (`_SENSITIVE_KEY_SUFFIXES`, `:66-73`) and the bare `endswith("url")` check (`:94`). `pic` is upstream's own field name and clears both. |
| `videos` column | `tid`, `tname` | `type_id`, `category` | Upstream calls them `tid`/`tname`; a reader greps the API doc with the same word. |
| `videos` column | `desc` | `description` | Upstream field name; the whole point is traceability to the response. |
| DTO fields | `VideoSummary.author`, `.tid`, `.pic`, `.desc` | nested `owner` dataclass | The list response has no nested owner; a nested type would invent a shape upstream does not send. |
| Gateway method | `get_video_tags(bvid)` | `get_tags` | The module already has `get_subtitle_tracks` / `fetch_subtitle_segments`; a bare `get_tags` reads as if it tags something. |

## Current state (verified 2026-09-26 at `9d530cd`)

What the pipeline persists **today**, upstream-derived: exactly **10 scalar columns**.

| Table | Upstream-derived columns | Anchor |
|---|---|---|
| `videos` | `bvid`, `aid`, `mid`, `title`, `pubdate` | `storage/schema.sql:10-19` |
| `video_parts` | `bvid`, `page_index`, `cid`, `title`, `duration_ms` | `storage/schema.sql:21-35` |
| `bilibili_users` | `mid` + `display_name` (a **placeholder**) | `storage/schema.sql:3-8` |

The five measured defects this plan addresses, each with its anchor:

1. **`display_name` is `str(mid)`.** `_user_record` (`services/metadata_ingest.py:98-108`) builds
   `UserRecord(..., display_name=str(mid), ...)`; the live store holds `display_name = "23191782"` where
   upstream calls the user `未明子`. `upsert_user` (`storage/database.py:292-304`) will store whatever it is
   given, and `v_video_parts.user_name` (`schema.sql:125-140`) projects it.
2. **The tag endpoint is never called.** `grep -rn 'tags' src/` finds no call; only two endpoint
   descriptors are imported (`bilibili_api_gateway.py:93`, `:104`). `Video.get_tags`
   (`bilibili_api.py` package, `video.py:336-360`) exists but is not bound, and it would trigger a
   `get_info` call when the cid is uncached — the descriptor-level call with `bvid` alone avoids that.
   Verified live 2026-09-26: `GET /x/web-interface/view/detail/tag?bvid=BV11p5qzAE6s` returns `code 0` with
   `[{tag_id: 943, tag_name: "爱情", ...}, {tag_id: 11128717, tag_name: "人类解放", ...}]` using only
   `User-Agent` + `Referer`, **no cookie**.
3. **The md frontmatter `title` is the part title.** `cli.py:1477` sets `"title": part["part_title"]`;
   `services/manifest_derivation.py:92` and `services/transcript_projection.py:261` do the same. Measured on
   the live store: 63 parts, 53 with `part_title == videos.title`, **10 divergent** — e.g. `BV18XXcBnEz6`
   part `哲学课3` vs video `【哲学进阶】现代哲学 《第一哲学沉思录》第二讲 第二个沉思（上）`. The video
   title is already reachable: `list_stored_transcripts` (`database.py:1205-1250`) already joins
   `JOIN videos AS vd ON vd.bvid = vp.bvid` **for `vd.pubdate`**.
4. **`x/web-interface/view` returns 45 top-level keys; the one call that touches it keeps only `aid`.**
   `get_completed_video_summary` (`bilibili_api_gateway.py:586-603`) returns early when `summary.aid is not
   None` — which is every row today (60/60 in the live store) — and `_complete_summary_from_detail`
   (`:488-522`) reads `aid`, `owner.mid`, `bvid` and drops the other 41, including `tid`, `tname`, `pic`,
   `desc`, `stat`, `dimension`.
5. **`videos.title` never reaches an artifact.** See (3).

**Consumers that must be updated together** (a field added only to the schema reaches no reader):
`archive.py:488-496` (frontmatter) · `export.py:17-33` (`STANDARD_CSV_COLUMNS`) ·
`search_index.py:563-565` (FTS5 columns — **conditional**: touched only if the tag set is to be searched; left alone by decision, since tags are unrendered and `20260928-transcript-search` owns that layer) · `services/manifest_derivation.py:71-97` (`row_for_part`) ·
`services/transcript_projection.py:230-282` (`projection_row`).

## Task 1: The uploader's own name — slice A of the original Task 1

**Line-number basis for this section: symbols, not offsets.** A fix round moves lines, so this section
> names functions and parameters rather than pinning line numbers; where a number survives it is dated. Post-fix
> HEAD is `8c1a77d` (`_user_record` module-level; `_record_collected_page` and the page loop inside
> `MetadataIngestor._collect`; `ensure_user` inside `MetadataRepository`).

**Status: Done (2026-09-26, `33cb0c4`; L2 review fixes on top, same branch).** The L2 task review found one
Critical on this slice (an observation-free run reverted `display_name` to `str(mid)`), plus one missing
store-side negative control and three minor prose/signature items; the fixes and their regression pins are
recorded below the delivered-files list.

**Effort (agent-oriented):** S

**Split point (taken).** The original split point read: *if the frontmatter pin's update turns out to require
touching more than `tests/test_archive_md.py` … stop after the `bilibili_users.display_name` half and report —
it becomes two tasks.* That condition fired: the `video_title` half also owes the store SELECT, the writer
entry, `archive.write_archive`, the manifest row, the projection row, the 24→25 frontmatter pin **and** two
transcript-repository tripwires. It is a separate deliverable and now stands as **Task 2** below.

**What shipped in this slice:** `VideoSummary` gains an optional `author`; the list normalizer reads it off
the vlist item and rejects a present-but-empty value; `_complete_summary_from_detail` carries it through
instead of dropping it; `metadata_ingest._user_record` records it as `bilibili_users.display_name` and falls
back to `str(mid)` only when upstream sent no name. An archived transcript can now name its uploader instead
of repeating the owner mid.

**Files (as delivered):**
- `bilibili-asr-archive/src/bili_asr/sources/models.py` — `VideoSummary.author: str | None = None` (`:83`),
  plus the `_text` guard when it is present (`:92-93`).
- `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` — `_normalize_video_summary_item` reads
  and validates `author` (`:193-205`); `_complete_summary_from_detail` preserves it (`:508`, `:538`).
- `bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py` — `_user_record(mid, moment, author)`
  at the module's top level (`author` has **no default** after the C1 review fix, so a pre-fetch caller must say
  `author=None` explicitly), `display_name=str(mid) if author is None else author`, and the **run-scoped**
  `observed_author` so a later page omitting the name cannot reset a label — the latch lives in
  `MetadataIngestor._collect`. The run-start write uses
  `MetadataRepository.ensure_user`: it creates the row the run and cursor foreign keys need and never rewrites
  one, and a page whose run has observed no name writes no user row at all.
- `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` — the fixture pages carry `author` as a
  **sixth** key: `make_vlist_item` emits six keys, so the "five-key default shape" this bullet first claimed
  is what the C1 review had to correct. **50** call sites at `33cb0c4` (46 at `9d530cd`), none of which broke,
  because the DTO field is optional.
- `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` — 111 new lines at `33cb0c4`: the author-read case,
  the absent-rather-than-invented case, and the completion-path preservation case. The L2 review added the
  blank-author blast-radius case and corrected this file's stale call-site count.
- `bilibili-asr-archive/tests/test_metadata_ingest.py` — the `_summary` factory gains `author`.
- `bilibili-asr-archive/tests/test_metadata_e2e.py` — **two pre-existing assertions re-derived on purpose**
  (`:188` and `:255`, both moved from the `str(MID)` placeholder to the real name).

**Design note — `author` is OPTIONAL on the DTO, contrary to this plan's first draft.** The first draft made
it required. That would have broken **46** `make_vlist_item` call sites (the builder emitted five keys before
this slice added `author` as its sixth), plus
`_complete_summary_from_detail`, which rebuilds the DTO at `:516-522` and would have had to invent a value it
does not receive. Optional keeps every existing construction valid, and the `str(mid)` fallback belongs in the
ingestor — which is the only layer that owns the user record and can tell "upstream sent no name" from
"upstream sent this name". (The optionality is what let all 50 call sites keep compiling; the sixth key means
the count in the delivered bullet above, not the five-key shape, is the fact.)

**Gate evidence (at `33cb0c4`):** `python -m pytest tests/test_bilibili_api_gateway.py tests/test_archive_md.py
tests/test_transcript_repository.py` → **473 passed, 1 skipped**. Full suite → **1562 passed, 123 skipped**.
7 files changed, 205 insertions, 16 deletions.

**Gate evidence (after the L2 review fixes):** the assigned five-file gate → **508 passed, 1 skipped**
(503 at `33cb0c4`); full suite excluding `tests/test_asr_qwen.py` → **1568 passed, 123 skipped** (1562 at
`33cb0c4` — the 6 new cases are the C1 cross-run pins, I1's negative control, the M3 blast-radius case and the
`ensure_user` contract case). 5 files changed, 340 insertions, 24 deletions.

**Run gates from the feature worktree with `PYTHONPATH="$PWD/src"`.** The shared venv's editable install
points at the **primary checkout's** `src`; a bare `pytest` from the worktree silently imports unmodified
code and would report green against the wrong tree.

---

## Task 2: The video title — slice B of the original Task 1

**Effort (agent-oriented):** M

**Split point:** If the frontmatter pin turns out to need a second pinned key list or a golden file beyond
`tests/test_archive_md.py`, stop after the store-and-carry half (Steps 1–3: `list_stored_transcripts` →
`cli.py` writer entry → `archive.write_archive`) and report. The publishing half then becomes its own task.
Do **not** stop earlier: a `video_title` that is stored but never reaches an artifact delivers no reader value.

**Depends on:** Task 1 (`33cb0c4`). This slice touches `cli.py`'s writer entry, which Task 1 already edited —
branch from Task 1's commit, not from the integration branch.

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py` (`list_stored_transcripts`, `:1238-1245` —
  add `vd.title AS video_title` to the SELECT)
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py` (`:1472-1481` — carry `video_title` from the row into the
  writer entry dict; the entry is built from `part`, so the row's new key must be threaded through)
- Modify: `bilibili-asr-archive/src/bili_asr/archive.py` (`write_archive`, `:478-499` — emit the key)
- Modify: `bilibili-asr-archive/src/bili_asr/services/manifest_derivation.py` (`row_for_part`, `:71-97`)
- Modify: `bilibili-asr-archive/src/bili_asr/services/transcript_projection.py` (`projection_row`, `:230-282`)
- Test: `bilibili-asr-archive/tests/test_archive_md.py` — **the 24-key pin must become 25** *(done in Task 2; the old `:296-333` anchor is itself stale — the
  function now starts at `:297` and the assertions sit at `:335-343`)*,
  and `assert len(front) == 24` (`:334`) with it. *(Both assertions are now 25 in the shipped file; the old `:334` anchor is stale.)* This is the deliberate, pinned format revision of compass
  **D4**; the new key goes beside `title`, never replacing it.
- Test: `bilibili-asr-archive/tests/test_transcript_repository.py` — **two** tripwires, both flip on purpose
  when the SELECT gains a column: the expected-row builder `_stored_row` (`:2102-2140`) and the explicit
  `set(rows[0].keys()) == {...}` assertion (`:2180-2195`). Extend both in the same commit; never drop one.
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`, `tests/test_metadata_ingest.py` — the two
  `_summary` factories gain `video_title` where a case needs it.

**Steps:**

- [x] **Step 1: Write the failing tests.** Add the artifact-side case to `tests/test_archive_md.py`
  (`test_write_archive_names_the_video_title_beside_the_part_title` — the pre-split Task 1 text carried it, and
  this plan's rewritten Task 1 no longer does, so write it here rather than moving it) and add the
  store-side proof: a `list_stored_transcripts` call whose returned row carries `video_title` equal to the
  video's own title while `part_title` stays the part's — the two must be independently assertable, because
  conflating them is exactly what D5 forbids.

- [x] **Step 2: Run the tests — expect FAIL.** Expect `KeyError: 'video_title'` at the artifact and a
  key-set mismatch at the repository pin.

- [x] **Step 3: Minimal implementation.** Add the column to the SELECT; thread it through the writer entry;
  emit it in `write_archive`; carry it in the manifest row and the projection row. Update the two repository
  tripwires and the 24→25 pin in the same commit.

- [x] **Step 4: Run the affected tests — expect PASS.**

```
PYTHONPATH="$PWD/src" python -m pytest tests/test_archive_md.py tests/test_transcript_repository.py tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v
```

- [x] **Step 5: Commit.**

**Verification gate:** the Step 4 command green, with the key-set pin reading 25 and both repository
tripwires extended.

**Run the gate from the feature worktree with `PYTHONPATH` set** — the shared venv's editable install points
at the primary checkout's `src`, so a bare `pytest` from the worktree silently imports unmodified code and
would pass against the wrong tree.

**Decision (2026-09-26, closing L2 I1 — `task-2-review.md`): the chain path publishes `video_title: ""` by
design; emit, never omit.** Four callers reach `write_archive` with a `row_for_part` row that has no
`video_title` — the chain/ASR path (`cli.py:2266`, `:2371`, `:2473`; `coordinator.py:492`, `:593`) — because
manifest rows are unchanged (deviation 1, deferred manifest half). Those runs publish an empty key rather than
a shorter block, because both pins of the published key set are equality-based: the ordered 25-key list plus
`assert len(front) == 25` (`tests/test_archive_md.py`), and `assert set(frontmatter) == FRONTMATTER_KEYS`
(`tests/test_published_projection_readers.py`). Omitting the key on that arm would make the artifact a
different published shape and weaken D4's "deliberate, pinned" contract; the three siblings on the same line
(`title`/`date`/`duration_s`) emit their empty default the same way. Pinned by
`test_write_archive_publishes_a_uniform_key_set_without_a_video_title`.

**Known reader-visible gap (not a completed delivery):** a chain-produced artifact says `video_title: ""`
until the deferred manifest half (`row_for_part`/`projection_row`) gives the row a real value. The md artifact
is the only surface that carries the key at all; closing that gap is the PM's decision problem per the same
review (its "What the PM must do next" §1/§2), not a code defect in this slice.

---

## Task 3: The tag call and its table

**Effort (agent-oriented):** M

**Split point:** If the fake-upstream seam cannot express a second endpoint without restructuring
`FakeUpstreamScript` (`tests/fixtures/fake_bilibili_gateway.py:277+`), stop and report after Step 4 with the
seam unmodified — the seam change becomes its own task rather than an improvised rewrite.

**Files:**
- Create: `bilibili-asr-archive/src/bili_asr/storage/schema.sql` change — `video_tags` table (no index; see Step 3)
- Modify: `bilibili-asr-archive/src/bili_asr/storage/models.py` (`VideoTagRecord` dataclass)
- Modify: `bilibili-asr-archive/src/bili_asr/sources/models.py` (`VideoTag` DTO)
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py` (import `_TAG_ENDPOINT`,
  add `get_video_tags(bvid)`)
- Modify: `bilibili-asr-archive/src/bili_asr/services/metadata_ingest.py` (fetch tags per **video**, once,
  cached per bvid within the run; persist after the part upserts)
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py` (`MetadataRepository.upsert_video_tags`,
  under the same transaction as the video upsert)
- Test: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` (add the call name to
  `DOCUMENTED_METADATA_CALLS` **and** a scripted response),
  `bilibili-asr-archive/tests/test_bilibili_api_gateway.py` (the exact-set pin — measured at `:2418` on this branch; find it by the assertion, not the number),
  `bilibili-asr-archive/tests/test_storage_schema.py` (`EXPECTED_TABLE_COLUMNS` + `BASE_TABLES`), a new
  ingest test asserting tags land once per video
- Out of scope: `x/tag/archive/tags` (the richer unsigned alternative — a different call, a different
  shape; deliberately not taken), tag *writing* (`video.operate.add_tag`), per-part tags.

**Interfaces:**
- Consumes: `_TAG_ENDPOINT` (new, `VIDEO_API["info"]["tags"]`), `VideoTag`, `VideoTagRecord`,
  `MetadataRepository.transaction` (`storage/database.py:287`).
- Produces: `BilibiliGateway.get_video_tags(bvid: str) -> tuple[VideoTag, ...] | None` — `None` means "could
  not read this time" (risk control, transport failure) and `()` means "read it, and this video carries none"
  (compass **D16**);
  `MetadataRepository.upsert_video_tags(bvid, tags)` — idempotent, replaces the video's tag set.

- [x] **Step 1: Write the failing tests**

```python
# (1) tests/test_storage_schema.py — extend the declared contract.
#     ``test_schema_inspection_matches_the_declared_contract`` (:856-942) asserts FOUR
#     per-table maps, not two — each read as ``.get(table, ())``, so a missing entry fails
#     rather than being skipped.  Add "video_tags" to BASE_TABLES (:47) plus:
EXPECTED_TABLE_COLUMNS["video_tags"] = ["bvid", "tag_id", "tag_name", "tag_type"]
EXPECTED_FOREIGN_KEYS["video_tags"] = (("bvid", "videos", "bvid"),)
EXPECTED_PRIMARY_KEY_INDEXES["video_tags"] = (("bvid", "tag_id"),)
#     EXPECTED_UNIQUE_CONSTRAINTS (:198) needs NO entry: the composite PK is reported as a
#     primary-key index, not a unique constraint, so the map's () default already matches.
#     EXPECTED_INDEXES (:215) likewise needs none — do NOT add a CREATE INDEX (see Step 3).
```

```python
# (2) the exact-set pin comparing `DOCUMENTED_METADATA_CALLS` (`tests/fixtures/fake_bilibili_gateway.py:138`) to its literal tuple; measured at `:2418` on this branch — the exact-set pin moves by one.
#     The name is "video.tags" because the adapter issues it through the pin's endpoint
#     descriptor (video.json info.tags), the same way "video.get_info" records the detail
#     route.  Keep the existing pytest.raises control below the tuple: it is what stops
#     the allow-list from passing vacuously.
assert DOCUMENTED_METADATA_CALLS == (
    "space.arc.search",
    "video.get_info",
    "video.get_pages",
    "video.tags",
    "player.track_list",
    "subtitle.body",
)
```

```python
# (3) tests/test_metadata_ingest.py — the per-video caching pin.  This is the test that
#     earns the task: a per-part implementation passes every other check here.
def test_tags_are_fetched_once_per_video_not_once_per_part(tmp_root):
    """Three parts of one video must produce exactly ONE tag call.

    The regression is cheap to write and expensive to miss: the tag set is a
    property of the VIDEO, so a fetch inside the per-part loop pays 3x on this
    fixture and O(parts) on a long multipart series.
    """
    gateway = FakeGateway()
    gateway.script_page(1, _page(1, _summary("BV1MULTI"), observed_total=1))
    gateway.script_parts(
        "BV1MULTI",
        (_part("BV1MULTI", 0, cid=11), _part("BV1MULTI", 1, cid=22),
         _part("BV1MULTI", 2, cid=33)),
    )
    gateway.script_tags("BV1MULTI", (
        VideoTag(tag_id=943, tag_name="爱情", tag_type="old_channel"),
        VideoTag(tag_id=11128717, tag_name="人类解放", tag_type="old_channel"),
    ))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)

        assert gateway.tag_calls == ["BV1MULTI"]
        rows = connection.execute(
            "SELECT tag_id, tag_name FROM video_tags WHERE bvid = ? ORDER BY tag_id",
            ("BV1MULTI",),
        ).fetchall()
        assert [tuple(row) for row in rows] == [(943, "爱情"), (11128717, "人类解放")]
    finally:
        connection.close()
```

- [x] **Step 2: Run the tests — expect FAIL**

Run (from the feature worktree **with** the `PYTHONPATH` override — the shared venv's editable install points
at the primary checkout, so a bare `pytest` here grades the wrong tree):

`PYTHONPATH="$PWD/src" …/.venv/bin/python -m pytest tests/test_storage_schema.py tests/test_metadata_ingest.py tests/test_bilibili_api_gateway.py -k 'tag' -v`

Expected: `sqlite3.OperationalError: no such table: video_tags`; an allow-list mismatch naming the
five-name tuple; `AttributeError: 'FakeGateway' object has no attribute 'tag_calls'` (that attribute is part
of this task's seam extension, see Step 3).

- [x] **Step 3: Minimal implementation**

Add to `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS video_tags (
    bvid TEXT NOT NULL,
    tag_id INTEGER NOT NULL CHECK (tag_id > 0),
    tag_name TEXT NOT NULL,
    tag_type TEXT NOT NULL,
    PRIMARY KEY (bvid, tag_id),
    FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE RESTRICT
);
```

A **new table** deliberately: per Global Constraints it is live-additive on an existing `archive.db`,
whereas a new `videos` column is not. `upsert_video_tags` deletes the video's rows and inserts the observed
set inside the caller's transaction, so a re-run converges rather than accumulating.

**No `CREATE INDEX`.** The composite primary key `(bvid, tag_id)` already serves this task's only declared
query — measured: `EXPLAIN QUERY PLAN SELECT tag_id, tag_name FROM video_tags WHERE bvid = ?` gives
`SEARCH video_tags USING INDEX sqlite_autoindex_video_tags_1 (bvid=?)`. A separate index would be additive
per the storage contract, but `EXPECTED_INDEXES` (`tests/test_storage_schema.py:215`) pins the declared-index
set per table, so it would have to be registered for no query benefit. The `## Files` line below says "table
+ its index"; the index half is **dropped**.

Add `_TAG_ENDPOINT = VIDEO_API["info"]["tags"]` beside the two existing descriptor imports and issue the
call through `Api(**api, credential=self.credential).update_params(bvid=...).result` with **no credential
requirement** — the endpoint descriptor's `verify` is `false` and the live probe confirms it answers
anonymously. Normalize into `VideoTag` with the same `GatewayShapeError` discipline as the sibling
normalizers; a missing `tag_id`/`tag_name` is a bounded shape error.

**Retry-free degradation is part of this step.** A tag fetch that hits risk control (`-352`, `412`) or any
transport failure must record **no tags** and let the run continue — the owner's metadata is not worth
failing an ingestion run over, and the measured 412 (§ Global Constraints, "Upstream politeness") shows this
is reachable. **"No tags" means "no observation", not "an empty set"** (compass **D16**, 2026-09-27): return
**`None`** on those errors — keep `()` for the honest empty inventory the normalizer returns for `data: []`,
per the signature in `## Interfaces`. The ingestor must map `None` to **omitting the bvid key** from the
page's tag sets rather than handing over an empty list, so `record_page`'s existing non-destructive treatment
of a missing key applies and a degraded re-run leaves the tags a previous run stored **untouched**. A
**genuine** empty observation is still a key present with an empty iterable and still clears the video's rows
(AC 3 — a second run replaces the set rather than appending); a later successful collection still refreshes it
(compass D11). Log the bounded code through the existing error-code path, never the raw response. The three
comments that currently promise the empty tuple — the `BilibiliGateway` Protocol comment above
`get_video_tags` (`sources/models.py`), the run-scoped cache comment in `metadata_ingest.py`, and the
`_observed_tag_sets` docstring that documents the conflation as deliberate — must be reconciled to the
distinguishable return in the same commit; each one is false once the signature changes.

**Seam extension (required, in this task).** `FakeGateway` (`tests/fixtures/fake_bilibili_gateway.py:325`)
and `FakeUpstreamScript` (`:277`) must both learn the new call, exactly as they already do for the two
subtitle routes:
- `FakeUpstreamScript`: a `tags_response` / `tags_error` script pair plus a `tag_calls: list[str]` recording
  list, mirroring `parts_calls` (`:348`) and `completion_calls` (`:349`).
- `FakeGateway`: `script_tags(bvid, tags)` + a `tag_calls` list, mirroring `script_subtitle_tracks` (`:373`)
  and `listing_cids` (`:351`).
Without both, the caching test in Step 1 cannot observe the call count, and the seam would silently accept
a per-part implementation.

- [x] **Step 4: Run the affected tests — expect PASS**

Run (same `PYTHONPATH` override as Step 2):

`PYTHONPATH="$PWD/src" …/.venv/bin/python -m pytest tests/test_storage_schema.py tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v`

- [x] **Step 5: Commit**

## Task 4: Category and cover from a response already received

**Effort (agent-oriented):** M

**Split point:** If `tid` turns out to be absent from the list response (see the evidence note below —
`make_vlist_item` currently carries **none** of `typeid`, `pic`, `description`), stop after Step 4 with the
fixture extension plus the `pic`/`desc` half, and report — the category source decision (list item vs the
view call) then needs a fresh call-count decision, which is PM's, not the implementer's.

**Evidence note — the fixture does NOT currently prove these fields exist.** Unlike Tasks 1-2, this task's
premise rests on a **live probe** (2026-09-26), not on a recorded fixture:
`GET /x/web-interface/view?bvid=BV11p5qzAE6s` returned 45 top-level keys including `tid: 124`,
`tid_v2: 2186`, `pic`, `desc`/`desc_v2`, `dimension`, `stat` (13 keys) and `pages[]` (10 keys per element).
The `arc/search` vlist item was separately observed with 38 keys including `typeid`, `pic`, `description`,
`author`, `length`, `play`, `comment`, `video_review` — but **that observation is two-of-three**: the third
attempt returned HTTP 412, and `.tmp/up-videos-coordinate-4.json` is a derived coordinate file, not a raw
response. So:

- `make_vlist_item` (`tests/fixtures/fake_bilibili_gateway.py`) must be extended with the literal defaults
  this task depends on (`typeid`, `pic`, `description`) — otherwise the test proves only that the normalizer
  can read a dictionary the test itself invented, which is the `absence-assertion-negative-control` trap
  (`{KNOWLEDGE_DIR}/testing-patterns/absence-assertion-negative-control.md`) in reverse.
- The implementer must state in the Completion Report which shape was verified against a **fixture** and
  which against the **live probe**, rather than letting the two borrow each other's authority.

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/schema.sql` — **no column change is possible here**
  (see the STOP condition); the fields go into a new child table
- Create: `bilibili-asr-archive/src/bili_asr/storage/schema.sql` change — `video_details` table
- Modify: `bilibili-asr-archive/src/bili_asr/sources/models.py` (`VideoSummary.pic`, `.desc`, `.tid`)
- Modify: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py`
  (`_normalize_video_summary_item`)
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py` (`upsert_video_details`)
- Modify: `bilibili-asr-archive/tests/fixtures/fake_bilibili_gateway.py` (`make_vlist_item` literals)
- Test: `bilibili-asr-archive/tests/test_storage_schema.py` — **four maps, not one**:
  `EXPECTED_TABLE_COLUMNS["video_details"] = ["bvid", "pic", "desc", "tid", "observed_at"]`
  (**unquoted `desc`** — quoting the DDL keyword does not change `PRAGMA table_info`),
  `EXPECTED_FOREIGN_KEYS["video_details"] = (("bvid", "videos", "bvid"),)`, and
  `EXPECTED_PRIMARY_KEY_INDEXES["video_details"] = (("bvid",),)`, plus `"video_details"` in `BASE_TABLES`
  (`:47`). `EXPECTED_UNIQUE_CONSTRAINTS` and `EXPECTED_INDEXES` need no entry (both default to `()` and this
  table declares neither) — each map is read as `.get(table, ())` at `:856-942`, so a missing entry fails
  rather than being skipped.
- Test: `bilibili-asr-archive/tests/test_bilibili_api_gateway.py`, `tests/test_metadata_ingest.py`
- Out of scope: the cover's **export** policy (`export.py:174-177` will redact the URL — see below, and compass D12); resolving
  `tid` → a human-readable `tname` (upstream returned `tname`/`tname_v2` as **empty strings** for every
  probed video on 2026-09-26, and the pin's local `data/video_zone.json` table has no entry for the
  observed `tid_v2` values); `stat` counters.

**STOP conditions:**
- If a Task author concludes the fields belong on the existing `videos` table, **STOP**. `initialize_schema`
  runs `CREATE ... IF NOT EXISTS` only, so a new `videos` column is silently absent on every existing
  `archive.db` and its first `INSERT` raises `sqlite3.OperationalError: table videos has no column named
  ...`. Adding it would force every operator to delete and rebuild the store. Use a child table.
- If `tid` is not present in the list response the fixtures actually record, **STOP** and report rather than
  falling back to the WBI-signed `view/detail` call: that call returned `-352 风控校验失败` unsigned on
  2026-09-26, and making it a hard dependency would put a risk-controlled endpoint on the ingest path.

**Interfaces:**
- Produces: `video_details(bvid, pic, desc, tid, observed_at)`, **one row per video, upserted on every
  collection that observed at least one of `pic`/`desc`/`tid`** (compass **D11**: the row is the *current*
  value, not a dated series — `observed_at` records the **last successful** collection and is overwritten by
  the next one; an observation carrying none of the three leaves the row and its stamp untouched, compass
  **D15**; a reader asking "what did upstream say on 2026-09-26" must get no answer from this schema, and the
  docstring must say so);
  `VideoSummary.pic: str | None`, `.desc: str | None`, `.tid: int | None` (all optional — the observed `desc`
  was empty for this UP's recent uploads, and absence is not an error here).

- [x] **Step 1: Write the failing test**

```python
# tests/test_metadata_ingest.py
def test_video_details_are_recorded_without_a_second_http_call(tmp_root):
    """``pic``/``desc``/``tid`` come from the page item the run already parses.

    The no-extra-call half is asserted on the recorded call list, not inferred:
    a run whose page_calls grew would be paying for these fields twice.
    """
    gateway = FakeGateway()
    gateway.script_page(
        1,
        _page(
            1,
            _summary("BV1DETAIL"),
            observed_total=1,
        ),
    )
    gateway.script_parts("BV1DETAIL", (_part("BV1DETAIL", 0),))
    gateway.script_page(2, _page(2, observed_total=1))
    connection = open_database(tmp_root)
    repository = MetadataRepository(connection)
    try:
        _ingestor(gateway, repository).collect_user_pages(MID, start_page=1)

        # No second call: the same two page fetches the run already made.
        assert [call[1] for call in gateway.page_calls] == [1, 2]

        row = connection.execute(
            'SELECT pic, "desc", tid FROM video_details WHERE bvid = ?',
            ("BV1DETAIL",),
        ).fetchone()
        assert row is not None
    finally:
        connection.close()


def test_video_details_are_refreshed_not_appended(tmp_root, _ingest_clock):
    """Compass D11: one row per video, overwritten by the next collection.

    This is the test that makes the ruling observable.  An implementer who
    reaches for an INSERT history (an obvious "improvement" while adding
    ``observed_at``) passes the test above and fails this one — which is the
    point, because the schema must not offer a reader what D11 says it does
    not promise.  Assert on the COUNT, not on ``observed_at`` alone: a
    timestamped series would also move the newest value.
    """
```

**The clock fixture is required, and the task must install it.** `tests/test_metadata_ingest.py` has **no**
clock fixture today (unlike `tests/test_metadata_cli.py:76-85` and `tests/test_metadata_e2e.py:85`, which
both monkeypatch `bili_asr.services.metadata_ingest._now` to a deterministic counter). Two collections
inside the same second — exactly what this test does — leave `observed_at` **unchanged**, so the Done
criterion "with `observed_at` advanced" is unsatisfiable without it. Add the same `_ingest_clock` fixture to
`tests/test_metadata_ingest.py` (monkeypatching `bili_asr.services.metadata_ingest._now`) and take it as a
test argument; do not weaken the assertion to `>=`.

**Pin the count, not just the fields.** The second test collects the same `bvid` twice (two ingestor runs
over the same scripted page) and asserts `SELECT COUNT(*) FROM video_details WHERE bvid = ?` equals **1**
while the value columns hold the *later* observation. A test that reads one row and stops cannot tell a
refresh from an append, so it would not pin D11 at all — and the Done criteria below restate the same count.

**Third case — the all-`NULL` observation (D15).** Add a third test in the same family: collect a `bvid`
whose item populates `pic`/`desc`/`tid`, then collect it again with an item carrying **none** of the three
(i.e. all-`NULL`), and assert the row is **unchanged** — the three values are still the first observation's
and `observed_at` has **not** moved. That is the assertion that distinguishes a guard from an adjective, and
it is what stops a later refactor from reinstating the unconditional `DO UPDATE SET`. A bvid whose *only*
observation is all-`NULL` writes **no row at all**; assert that too, so "leaves the row untouched" cannot be
satisfied by writing a row of `NULL`s.

The DTO-level half belongs in `tests/test_bilibili_api_gateway.py` beside Task 1's author cases, asserting
that a vlist item carrying `typeid`/`pic`/`description` populates the three DTO fields and that an item
**without** them leaves all three `None` (the negative control: without it, the test proves only that the
normalizer can read what the test invented).

- [x] **Step 2: Run the test — expect FAIL**

Run: `python -m pytest tests/test_metadata_ingest.py -k 'video_details' -v`

- [x] **Step 3: Minimal implementation**

```sql
CREATE TABLE IF NOT EXISTS video_details (
    bvid TEXT PRIMARY KEY,
    pic TEXT,
    "desc" TEXT,
    tid INTEGER CHECK (tid IS NULL OR tid > 0),
    observed_at INTEGER NOT NULL,
    FOREIGN KEY (bvid) REFERENCES videos(bvid) ON DELETE RESTRICT
);
```

**One row per video, and it is refreshed (D11).** `upsert_video_details` writes
`ON CONFLICT(bvid) DO UPDATE SET`, so a second collection of the same bvid replaces the row rather than
adding one: `SELECT COUNT(*) FROM video_details WHERE bvid = ?` stays `1` forever. Say that in the
docstring — including the sentence that a reader must not treat the table as a history. This is the
behaviour the plan is allowed to promise and the only one it does.

**`observed_at` means "last *successful* collection" — make that a condition, not an adjective (D15).**
The three value columns are all nullable (an absent `desc` is legitimate, above), so an unconditional
`DO UPDATE SET` can overwrite a populated row with `NULL`s and advance the stamp — recording "nothing was
true at T" where the collection established no such thing, in the column whose meaning D11 fixes. Write
the upsert so the row and its stamp advance **only when the incoming observation carries at least one of
`pic` / `desc` / `tid`**; an all-`NULL` observation leaves the existing row and its `observed_at`
**untouched** (and records nothing for a bvid that has no row yet). State that rule in the docstring in
one sentence, so the guard is not re-derived by the next reader. The grain is unchanged: one row per
video, refreshed — D15 constrains *when* the stamp moves, not what the table holds.

`"desc"` is quoted because `desc` is a SQL keyword and the column keeps upstream's own field name per
`## Naming decisions`. Quoting changes no observable: `PRAGMA table_info` still reports the column as
`desc`, so `EXPECTED_TABLE_COLUMNS["video_details"]` lists it unquoted. Quote it the same way in every
`SELECT` the task writes.

`pic` is named for upstream's own field per `## Naming decisions`, so `export`'s `_url`-suffix rule does not
silently drop the key. Note in the docstring that `export` will still redact its **value** and that this is
**intended and permanent for this iteration**: compass **D12** rules the cover store-only, so the DB carries
the URL and the shareable surface does not. Do **not** modify `export.py` in this plan, and do not add `pic`
to an export allow-list — a cover that must appear in an export is a **new** decision (D12's revisit
trigger: a named reader that needs it outside the archive), not an implementation detail of this task.

- [x] **Step 4: Run the affected tests — expect PASS**

Run: `python -m pytest tests/test_storage_schema.py tests/test_metadata_ingest.py tests/test_bilibili_api_gateway.py -v`

- [x] **Step 5: Commit**

## Task 5: Surface the new fields on the published artifact

**Effort (agent-oriented):** M

**Split point:** If more than three additional pinned key lists are discovered (the frontmatter pin, plus
`STANDARD_CSV_COLUMNS`, plus the FTS column list), stop after the frontmatter and the manifest row and
report; the index/export surface becomes its own task.

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/archive.py` (`write_archive` frontmatter, `:488-496`)
- Modify: `bilibili-asr-archive/src/bili_asr/export.py` (`STANDARD_CSV_COLUMNS`, `:17-33`)
- Modify: `bilibili-asr-archive/src/bili_asr/search_index.py` (FTS5 column list, `:563-565`) — only if the
  tag set is to be searched; otherwise leave it and say so
- Test: `bilibili-asr-archive/tests/test_archive_md.py` (the key-set pin), `tests/test_export.py`
  (or the existing export suite) for the CSV header pin, `tests/test_search_index.py` if FTS changes
- Out of scope: `docs/` and `README.md` prose (the compass routes documentation to
  `writing-specialist` in Phase 1, not to an implementer); the export redaction policy.

**Interfaces:**
- Consumes: the rows produced by Tasks 1-3.
- Produces: the published artifact carries `video_title`, and the video's tags/category are reachable from
  the store by `bvid`.
- **Product ruling (seat 1, 2026-09-26 — settled, not a recommendation): tags are NOT rendered into the md
  frontmatter, now or as a stretch goal of this task.** The frontmatter key set is a *pinned, ordered* format
  contract (D4) and a variable-length tag list would make it unstable across videos — two archives could not
  be compared key-for-key, and the pin would have to move from "exactly N keys" to a weaker shape. The store
  holds the tag set queryably by `bvid`, which is what the operator's complaint asked for. A rendered tag
  line is a **new format decision**, and this plan does not make it. Task 5 therefore renders `video_title`
  only, plus whatever CSV/FTS surface the task's own Step 1 pins.

- [x] **Step 1: Write the failing test** — pin whatever this task actually renders (frontmatter key and/or
  CSV column), with the expected and observed values named in the test docstring.
- [x] **Step 2: Run it — expect FAIL.**
- [x] **Step 3: Minimal implementation** — thread the fields; update every pinned list in the same commit.
- [x] **Step 4: Run the affected suites — expect PASS.**
- [x] **Step 5: Commit**

## Verification plan

| Task | Gate | Expected |
|---|---|---|
| 1 | `python -m pytest tests/test_bilibili_api_gateway.py tests/test_archive_md.py tests/test_transcript_repository.py -v` | **Done 2026-09-26** — 473 passed, 1 skipped; the author cases pass and no pin moved |
| 2 | `python -m pytest tests/test_archive_md.py tests/test_transcript_repository.py tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v` | the key-set pin passes at **25**; both repository tripwires extended; `video_title` independent of `part_title` |
| 3 | `python -m pytest tests/test_storage_schema.py tests/test_bilibili_api_gateway.py tests/test_metadata_ingest.py -v` | `video_tags` in the declared contract; the call-set pin lists exactly six names; one tag call per video |
| 4 | `python -m pytest tests/test_storage_schema.py tests/test_metadata_ingest.py tests/test_bilibili_api_gateway.py -v` | `video_details` present and pinned in all four contract maps; no extra HTTP call in `script.page_calls`; two collections of one bvid leave exactly **one** row with `observed_at` advanced (D11); an all-`NULL` observation leaves row and stamp untouched (D15) |
| 5 | the suites named in Task 5 | every pinned list updated together; the artifact carries the new key |

Not a gate here: a local full-suite run (CI owns it), and any real-machine CLI E2E (a separately requested
`mstar-e2e` workflow, never a development plan's task).

## Acceptance criteria (compass AC 1-3, made checkable)

Each row is verifiable by a reader who never read the investigation: the command is exact, the expected
observation is exact, and no row can be satisfied by prose. Run every command from
`bilibili-asr-archive/`. "Fresh ingest" means a run against a root whose `archive.db` has no rows for that
`bvid` — the fake upstream is the only channel (no test may reach the network).

| # | Compass AC | Check | Expected |
|---|---|---|---|
| 1 | AC 1 — the uploader's real display name is stored, not `str(mid)` | `python -m pytest tests/test_metadata_e2e.py -k fetch_meta -v` after its `display_name` assertion is updated, **plus** a direct read: `sqlite3 <root>/archive.db "SELECT mid, display_name FROM bilibili_users"` on a root ingested from a page item carrying `author: "未明子"` | the row reads `未明子`; the live corpus value would be `未明子`, never `23191782`. An item with **no** `author` still stores `str(mid)` — that fallback is the negative control and **must be a separate case** (`test_page_without_an_author_stores_the_owner_mid_placeholder`), and the cross-run cases (`test_no_flag_rerun_observing_no_author_keeps_the_stored_display_name`, `test_risk_interrupted_run_keeps_the_display_name_it_never_observed`, `test_collected_page_without_an_author_keeps_the_stored_display_name`) pin that a run which observed no name **cannot revert** a name an earlier run stored |
| 2 | AC 2 — the artifact carries the video title and `title` still means the part title | `python -m pytest tests/test_archive_md.py -v` (the key-set pin at its updated length **and** the new `video_title` case) | the md frontmatter contains both `title` = the part title (`哲学课3` in the fixture) and `video_title` = the video title; the key-set pin asserts the new exact ordered list, and the commit body names it a deliberate format revision |
| 3 | AC 3 — tags are keyed `(bvid, tag_id)` and fetched once per video | `python -m pytest tests/test_metadata_ingest.py -k "tag_ or tags" -v` (measured: **8 of 39** collected — every tag case; the row's original `-k tags` selected only **1**, and `-k tag` selects 9 of which one is the unrelated `test_parts_stage_failure…`), then `sqlite3 <root>/archive.db "SELECT bvid, tag_id, tag_name FROM video_tags ORDER BY bvid, tag_id"` | the three-part fixture records exactly **one** tag call (`gateway.tag_calls == ["BV1MULTI"]`) and the table holds one row per observed tag; a second run of the same bvid replaces the set rather than appending; and a run whose tag call **degrades** leaves the rows a previous run stored in place, while a genuine empty observation still clears them (compass **D16**) |

Not in this list and not claimed anywhere in this plan: a retention or persistence change (that is the audio
plan, and per compass D6 retention is already the shipped default), a point-in-time metadata snapshot
(compass D11 — the row is refreshed), a cover visible in an export (compass D12 — it is not), and any
rendered tag list in the md frontmatter (ruled out above).

## Done criteria

- [ ] `video_tags` and `video_details` are in `BASE_TABLES` + all four per-table maps the declared-contract
      test reads (`EXPECTED_TABLE_COLUMNS`, `EXPECTED_FOREIGN_KEYS`, `EXPECTED_PRIMARY_KEY_INDEXES`; the
      unique-constraint and declared-index maps need no entry) and
      `test_schema_inspection_matches_the_declared_contract` passes
- [ ] `DOCUMENTED_METADATA_CALLS` is exactly six names and the guard still rejects an outside call
- [ ] A 3-part video produces exactly **one** tag call (the per-video caching pin)
- [ ] The published md carries `video_title` and still carries `title` meaning the part title
- [ ] `bilibili_users.display_name` holds the observed author on a fresh ingest, not `str(mid)` — and still
      falls back to `str(mid)` on an item that carries no author
- [ ] `video_details` holds exactly **one** row per bvid after two collections of the same video, with
      `observed_at` advanced (compass D11 — the table is refreshed, not appended). **The test needs the
      `_ingest_clock` fixture added to `tests/test_metadata_ingest.py`** — that file has no clock patch
      today, so two collections in one second leave the stamp unchanged and this criterion unsatisfiable
- [ ] A collection carrying none of `pic`/`desc`/`tid` leaves an existing `video_details` row **and its
      `observed_at`** untouched, and writes no row for a bvid that has none (compass **D15** — the stamp
      means "last *successful* collection")
- [ ] No credential was added to any new call, and no stored field carries a signed URL
- [ ] **`export.py`'s redaction rules are unmodified** — `SENSITIVE_EXPORT_KEYS`,
      `_SENSITIVE_KEY_SUFFIXES` and `_is_sensitive_key` show no hunk, and no stored field
      became visible in an export because of this plan (compass **D12**). *Task 5 legitimately
      adds `video_title` to `STANDARD_CSV_COLUMNS` — that is this plan's own licence at Task 5's
      `## Files`, and D12 freezes the **redaction policy**, not the column list. The earlier
      wording ("`export.py` is unmodified") contradicted that licence and read as a criterion
      this plan could never pass; corrected 2026-09-27 after the Task 5 L2 review found it.*
- [ ] No tag list appears in the md frontmatter, and the frontmatter key set is pinned at its new exact
      length rather than loosened to a "contains" assertion
- [ ] `git diff --check -- <in-scope files>` exits 0 and no file outside the task lists changed
      (`git status --short`)

## Drift check

Written against `9d530cd`. Before Task 1, run:

```
git diff --stat 9d530cd..HEAD -- \
  bilibili-asr-archive/src/bili_asr/sources/ \
  bilibili-asr-archive/src/bili_asr/storage/ \
  bilibili-asr-archive/src/bili_asr/services/ \
  bilibili-asr-archive/src/bili_asr/archive.py \
  bilibili-asr-archive/src/bili_asr/cli.py
```

If any in-scope file moved, re-read the `## Current state` excerpts against live code before proceeding. On
mismatch → STOP.

## Open questions (owned, non-blocking)

**The two questions this plan used to carry were converged into compass decisions by seat 1 (2026-09-26)
and are withdrawn here. They are not open.** Plan-local ids are prefixed `M` so they cannot be confused with
the compass rows of the same old number.

| # | Question — **withdrawn, now decided** | Where the answer lives |
|---|---|---|
| `~~MQ1~~` | Point-in-time snapshot vs refresh-on-recollect? **Decided: refresh-on-recollect.** `video_details` keeps one row per video; `observed_at` records the last successful collection and is overwritten by the next one. A collection that observed none of the three value columns is not a successful observation and moves neither the row nor the stamp (**D15**, added by the architect review). This plan therefore stores no dated series and must never be described as one. | Compass **D11** + **D15**; Task 3's DDL and docstring restate both |
| `~~MQ2~~` | Should a stored cover URL survive `export`? **Decided: no.** The cover is store-only; `export`'s redaction rule is unchanged, and this plan modifies neither the key rule nor the value redaction. | Compass **D12**; Task 3's docstring note, plus `## Global Constraints` |

| # | Question (still open, not this plan's to answer) | Owner |
|---|---|---|
| MQ3 | Is one extra unsigned GET per video acceptable for a full-corpus run, given the observed `412` on `/x/space/wbi/arc/search` after two successes on 2026-09-26? A rate limit or a campaign-level cap may be owed. | PM |

## Engine lifecycle

- **Scoped sequence** — this plan row is advanced by the coordinator only, one engine verb per transition:
  `bind --coordinator` → `prepare` → `bind` → `progress` → `handoff` → `accept` → `integration-start` →
  Git merge → `integration-accept` → `complete`. No implementer or reviewer edits a snapshot row.
- **Evidence order** — compound disposition, PR identity and merge evidence are recorded **after** the row
  is `Done`; the engine refuses those writes while any plan row is not `Done`.
- **Precondition** — this row cannot be dispatched while iteration `iter-2026-09-metadata-audio-layout` is
  unregistered and `iter-2026-09-qwen3-asr-closeout` still holds its lease. If a dispatch is attempted
  before the compass `## Blocked By` clears, STOP and report to the coordinator rather than fabricating a
  terminal state.
