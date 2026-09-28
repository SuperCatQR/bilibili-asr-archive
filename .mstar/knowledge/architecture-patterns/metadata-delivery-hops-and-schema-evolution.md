---
module: bili-asr metadata path (gateway → DTO → record → schema → read → surface)
date: "2026-09-28"
problem_type: architecture_pattern
category: architecture-patterns
severity: high
plan_id: 20260926-video-metadata-enrichment
applies_when:
  - adding a metadata field to the archive, from the API response to the artifact a reader sees
  - deciding whether a new fact becomes a child table or a widened column
  - judging whether a field that is stored is actually delivered
  - wiring a sixth surface after the store already holds the value
  - pinning the schema contract maps for a new table
tags:
  - metadata-hops
  - delivery-checklist
  - schema-evolution
  - child-table
  - silent-column-absence
  - consumer-surfaces
  - format-revision
---

# A stored field is not a delivered field: six hops, and the schema rule that decides where it goes

## Context

Metadata enrichment for the archive looks like one change and is six. The iteration added four video-level
facts (the uploader's real name, the video's own title, the tag set, the category and cover) and the recurring
failure mode was a field that reached the store and stopped. Two distinct traps produced it:

**Trap 1 — the hop list is longer than it looks.** A field travels
`gateway normalizer → DTO → storage record → schema → SQL read → manifest/projection row →
frontmatter / FTS / CSV`. Skipping any hop yields a *different* symptom, and none of them is an error:

| Hop | File | If skipped |
|---|---|---|
| 1 Gateway | `src/bili_asr/sources/bilibili_api_gateway.py` | the field is never parsed out of the response |
| 2 DTO | `src/bili_asr/sources/models.py` | the field cannot leave the gateway |
| 3 Record | `src/bili_asr/storage/models.py` | the field cannot be validated for storage |
| 4 Schema | `src/bili_asr/storage/schema.sql` | the field has nowhere to go |
| 5 Read | `src/bili_asr/storage/database.py` | the field never leaves the store |
| 6 Surface | `archive.py`, `search_index.py`, `export.py`, `services/*.py` | the field exists but no reader sees it |

A field that stops at hop 4 is not delivered, and the plan's consumer list *is* the definition of done.

**Trap 2 — a new column on an existing table is silently absent.** `initialize_schema` executes only
`CREATE ... IF NOT EXISTS`, and `SchemaContractError` states the policy outright: *"The archive database is
rebuildable by policy, so there is no migration path."* Measured by running the product's own
`initialize_schema` on a scratch database that already existed: after appending a `description` column to
`videos` and a new table to `schema.sql`, reopening created the **new table**, did **not** create the
**column**, and the first `INSERT` naming it failed with `table videos has no column named description`.

## Guidance

1. **Write the hop list into the plan's consumer section and treat it as the done criterion.** Name the
   concrete files, not the layers. The metadata plan's `## Current state` lists all six surfaces for exactly
   this reason — a reader who only sees "add the field" will stop at the store.

2. **New video-level facts go into a child table keyed by `bvid`, never a widened column.**
   `video_tags(bvid, tag_id)` and `video_details(bvid, pic, "desc", tid, observed_at)` are the shipped shape.
   The rule is not stylistic: a widened column is silently absent on every existing `archive.db`, so the
   change appears to work in a fresh clone and fails on the operator's real store. Additive landing was
   verified against a database built from the pre-change schema bytes—the new table appears on the next open,
   no table is dropped, prior rows survive.

3. **Quote SQL keywords in DDL, and expect PRAGMA to report them unquoted.** `video_details` stores
   `"desc"`. `PRAGMA table_info` reports the column as `desc`, so the schema-contract map lists it **unquoted**
   while the DDL quotes it. Getting this backwards is a test failure that looks like a schema defect.

4. **The schema pin is a set of maps, and an undeclared table is silently unchecked.**
   `test_schema_inspection_matches_the_declared_contract` asserts, for every table in `BASE_TABLES`:
   `EXPECTED_TABLE_COLUMNS`, `EXPECTED_FOREIGN_KEYS`, `EXPECTED_PRIMARY_KEY_INDEXES`,
   `EXPECTED_UNIQUE_CONSTRAINTS`, `EXPECTED_INDEXES` (plus `EXPECTED_CHECK_ENUMERATIONS`). Most read
   `.get(table, ())`, whose empty default *fails*; **`EXPECTED_CHECK_ENUMERATIONS` iterates declared keys
   only**, so a table with a `CHECK` and no entry has that constraint unchecked. Measured: deleting
   `CHECK (tid IS NULL OR tid > 0)` from the DDL left the schema suite **39 passed, fully green**. Declare the
   entry, and prove it by deleting the constraint.

5. **An "additive" field is still a deliberate format revision — pin the exact new shape.** Adding
   `video_title` to the md frontmatter moved the pinned ordered key list 24 → 25. Pin the **ordered literal
   plus its length** (`assert len(front) == 25`), not a "contains" assertion; keep `title` meaning the *part*
   title and give the video's own title a sibling key. When the count is stated in prose, cite the pin beside
   it so the sentence defers to the assertion instead of drifting from it.

6. **A field's name at the boundary is the endpoint's, not yours.** The **list** endpoint spells the category
   `typeid` and the description `description`; the **view** endpoint spells them `tid`/`desc`. Reading the
   wrong key yields `None` forever while every test stays green, because a fixture that invents the wrong
   spelling validates only itself. Verify against a recorded payload — measured over 30 items: `typeid`/`pic`/
   `description` in 30/30, `tid`/`desc`/`tid_v2`/`tname` in 0/30.

7. **A blank upstream value is absence, not a value.** 25 of 30 recorded items carried an empty
   `description`. Map blank → `None` rather than storing `""` or `"-"`, because the store's own `_text`
   validator rejects an empty-after-strip value and the DTO would otherwise carry a fiction.

## Why This Matters

Each trap produces work that looks finished. A field stopping at hop 4 passes its own tests; a widened column
passes in a fresh clone; an unchecked `CHECK` passes because nothing reads it; a wrong endpoint spelling passes
because the fixture agrees with the code. The cost is discovered later, on the operator's real store, as a
missing column or a permanently-`None` field — at which point the fix is a schema decision, not a code edit.
The six-hop list converts "did this land?" into a checklist a reader can run.

## When to Apply

- Any change that carries a new fact from an API response into an artifact a human or a query reads.
- Before choosing between a child table and a widened column — the answer is almost always the child table,
  and the reason is the existing-store case, not modelling taste.
- When a schema test is being extended for a new table: update the declared maps, and check specifically
  whether `EXPECTED_CHECK_ENUMERATIONS` needs an entry (it is the one that does not fail loudly).
- When a frontmatter or CSV key set changes: pin the ordered literal and its length in the same commit.
- When adding a normalizer read: confirm the key against a recorded payload before writing the fixture.

## Examples

### Before — the field is stored, and nothing reads it

```python
# normalizer, DTO, record and schema all carry the category; the surface does not
item.get("typeid")            # hop 1 ✓
class VideoSummary: tid: int  # hop 2 ✓  ... and stops here for the reader
```

`SELECT COUNT(*) FROM video_details` returns rows, the store is correct, and no export or frontmatter key
exists — so the feature is invisible. The hop table says which file is missing.

### After — the hop list is the done criterion, and the pin is exact

```python
assert list(front) == [ ... ]   # the ordered literal
assert len(front) == 25         # and its length, pinned beside it
```

Plus, for the schema half: an `EXPECTED_CHECK_ENUMERATIONS["video_details"]` entry proven by deleting the
constraint (the suite must go red), and `EXPECTED_TABLE_COLUMNS["video_details"]` listing `desc` **unquoted**
while `schema.sql` quotes it.

## Evidence

- `.mstar/iterations/iter-2026-09-metadata-audio-layout/specs/metadata-coverage-contract.md` §1 (the hop
  table), §2 (the schema-evolution table, the silent-column measurement, and the map-by-map analysis of what
  each new table requires), §3 (which fields earned a place, and each exclusion's reason).
- The silent-column-absence measurement: `initialize_schema` on an existing scratch database after appending a
  column and a table — the table appears, the column does not, the first `INSERT` raises
  `table videos has no column named description`.
- The unchecked-`CHECK` measurement: `EXPECTED_CHECK_ENUMERATIONS` declares nine tables and its loop iterates
  declared keys only; deleting `CHECK (tid IS NULL OR tid > 0)` left `tests/test_storage_schema.py` at
  **39 passed**. Fixed in `2241575`, with the deletion now failing
  `test_schema_inspection_matches_the_declared_contract`.
- The endpoint-spelling trap: `.tmp/probe/arc_items.json` (30 items) — `typeid`/`pic`/`description` 30/30,
  `tid`/`desc`/`tid_v2`/`tname` 0/30; the shipped fix is `6c98a536`-reviewed `318c0ed`, whose normalizer reads
  `item.get("typeid")` and whose fixture uses the list spellings.
- The format revision: `tests/test_archive_md.py` ordered literal (`video_title` at position **3**, not 25 —
  position 25 is `cid`) and `assert len(front) == 25`; `export.py`'s `STANDARD_CSV_COLUMNS` gaining
  `video_title` at index 6.
- The child-table choice, measured: `video_details(bvid PK, pic, "desc", tid, observed_at)` with an FK to
  `videos`, verified additive on a database built from the pre-change schema bytes.

## See also

- `architecture-patterns/normalized-metadata-stack.md` — the stack this pattern sits inside; it describes the
  layers, this document is the delivery checklist that crosses them.
- `best-practices/completion-claims-need-live-evidence.md` — why a green suite did not catch the unchecked
  `CHECK` or the field that stopped at hop 4.
- `best-practices/degradation-vs-observation-third-state.md` — the write-side rule for a fetch that fails: the
  tag path's `None` vs `()` distinction.
- `testing-patterns/absence-assertion-negative-control.md` — the general form of "prove the constraint is
  checked by deleting it".
