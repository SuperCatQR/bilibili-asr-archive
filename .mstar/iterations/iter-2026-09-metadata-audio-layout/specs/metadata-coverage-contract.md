Promoted to: .mstar/knowledge/best-practices/degradation-vs-observation-third-state.md (D16 third-state ruling derived from the D15-adjacent degradation pattern; 2026-09-27 compound round)

# Metadata coverage contract

**Iteration:** `iter-2026-09-metadata-audio-layout` (registered `active` 2026-09-26; awaiting `locked`).
**Plan:** `20260926-video-metadata-enrichment`.
**Status:** draft spec — to be locked by the Phase-1 review chain when the iteration locks.
**Baseline:** `9d530cd`, 2026-09-26.

This contract states what the archive persists about a video, what it deliberately does not, and the rules
any addition must follow. It exists so a fifth metadata field does not get added by improvisation.

**The grain is decided: refreshed, not frozen (compass D11).** Every fact this contract admits is stored as
the **current** value, refreshed by the next collection; `video_details.observed_at` records the last
**successful** collection and is overwritten by the next one. Nothing here is a dated series, and no reader
may infer "what upstream said on date X" from the stored shape. That ruling is why the time-varying counters
below stay excluded rather than deferred, and it is the sentence any later addition must reckon with first.

**"Successful" is a condition, not an adjective (compass D15, added by the architect review 2026-09-26).**
Because every `video_details` value column is nullable, an unconditional `DO UPDATE SET` can overwrite a
populated row with `NULL`s and advance the stamp — asserting "nothing was true at T" where the collection
established no such thing. The write therefore advances the row and its `observed_at` **only when the
observation carries at least one of `pic` / `desc` / `tid`**; an all-`NULL` observation leaves an existing
row and its stamp untouched, and writes no row at all for a bvid that has none. The grain is unchanged — one
row per video, refreshed (D11); D15 constrains only when the stamp moves. A later addition that widens this
table inherits the same rule: a nullable column may not be blanked by an observation that did not observe
it.

## 1. The five-hop rule

A metadata field reaches a reader only if it is added at **every** hop, in this order:

```
gateway normalizer  →  DTO  →  storage record  →  schema  →  SQL read  →  manifest/projection row
   →  frontmatter / FTS / CSV
```

| Hop | File | If skipped |
|---|---|---|
| 1 Gateway | `src/bili_asr/sources/bilibili_api_gateway.py` | the field is never parsed out of the response |
| 2 DTO | `src/bili_asr/sources/models.py` | the field cannot leave the gateway |
| 3 Record | `src/bili_asr/storage/models.py` | the field cannot be validated for storage |
| 4 Schema | `src/bili_asr/storage/schema.sql` | the field has nowhere to go |
| 5 Read | `src/bili_asr/storage/database.py` | the field never leaves the store |
| 6 Surface | `archive.py`, `search_index.py`, `export.py`, `services/*.py` | the field exists but no reader sees it |

**A field that stops at hop 4 is not delivered.** The plan's `## Current state` names all six consumer
surfaces because that list is the definition of done.

## 2. Schema evolution rules (non-negotiable)

`initialize_schema` (`storage/database.py:154-172`) executes only `CREATE ... IF NOT EXISTS`, and
`SchemaContractError` (`:68-73`) states the policy: *"The archive database is rebuildable by policy, so there
is no migration path."* Therefore:

| Change | Effect on an existing `archive.db` | Verdict |
|---|---|---|
| New **table** | created on the next open | **Additive — preferred** |
| New **index** | created on the next open | Additive |
| New **view** | created on the next open | Additive |
| New **column** on an existing table | **silently absent**; the first `INSERT` naming it raises `sqlite3.OperationalError` | **Forbidden without an explicit rebuild decision** |
| Renamed/dropped column | same | Forbidden |

Verified 2026-09-26 by running the product's own `initialize_schema` on a scratch database: after appending
a `description` column to `videos` and a new table to `schema.sql`, reopening the existing database created
the new table, did **not** create the column, and the first `INSERT` failed with
`table videos has no column named description`.

**Consequence for this iteration:** new video-level facts go into **child tables** keyed by `bvid`
(`video_tags`, `video_details`), never into widened columns on `videos`.

**The pin is four maps, not one — verified 2026-09-26 against the test body.**
`test_schema_inspection_matches_the_declared_contract` (`tests/test_storage_schema.py:856-942`) asserts, for
every table in `BASE_TABLES` (`:47`): membership in that set, then `EXPECTED_TABLE_COLUMNS` (`:69`),
`EXPECTED_FOREIGN_KEYS` (`:173`), `EXPECTED_PRIMARY_KEY_INDEXES` (`:205`), `EXPECTED_UNIQUE_CONSTRAINTS`
(`:198`) and `EXPECTED_INDEXES` (`:215`). The first is an equality on the table-name set; the rest read
`.get(table, ())`, whose **empty default fails** rather than skipping the table. Measured against this
iteration's two new tables: the columns, foreign-key and primary-key-index entries are **required** for both
`video_tags` and `video_details`; the unique-constraint and declared-index maps need **no** entry (a
composite primary key is reported as a primary-key index, not a unique constraint, and neither table declares
a `CREATE INDEX`). Every schema change updates the required maps in the same commit or the suite fails.

A **new index** is additive by the table above, but a declared `CREATE INDEX` must be registered in
`EXPECTED_INDEXES` — so add one only when a query needs it. Neither table here does: `video_tags`' composite
primary key `(bvid, tag_id)` already serves `WHERE bvid = ?` (measured: `SEARCH video_tags USING INDEX
sqlite_autoindex_video_tags_1 (bvid=?)`).

## 3. What is persisted, and why each field earned its place

### 3.1 In scope for `20260926-video-metadata-enrichment`

| Field | Source | Extra HTTP call? | Why it earns its place |
|---|---|---|---|
| `author` (uploader display name) | vlist item's `author`; `x/web-interface/view`'s `owner.name` | **No** | `bilibili_users.display_name` currently stores `str(mid)` — measured: the live store holds `"23191782"` where upstream says `未明子`. A placeholder is worse than an absent field because it reads as data |
| `video_title` (artifact surface) | `videos.title`, reachable today via the join already present in `list_stored_transcripts` | **No** | The md frontmatter `title` is the **part** title; 10 of 63 measured parts carry a placeholder (`哲学课3`, `20260526-110802`) while the real title sits unread. This is the highest reader value for the lowest cost |
| `video_tags` (tag set) | `/x/web-interface/view/detail/tag` | **Yes — one unsigned GET per video** | The field the operator named. Cached per `bvid`, never per part |
| `tid` (category id) | vlist item / `view` call | **No** | Already in the response; cheap and stable |
| `desc` (video description) | vlist item's `description` / `view` call's `desc` | **No** | Already in the response. Kept under upstream's keyword-named spelling per the naming discipline; it must be written quoted (`"desc"`) in DDL and SQL — quoting does not change `PRAGMA table_info`, so the declared-contract column list keeps the bare name |
| `observed_at` (collection stamp) | the run's own clock, not upstream | **No** | The one column that makes **D11** readable from the store: it records the last **successful** collection and moves only when the observation carried at least one of `pic`/`desc`/`tid` (**D15**). It is deliberately *not* a series key and carries no index |
| `pic` (cover URL) | vlist item / `view` call | **No** | Already in the response; named `pic` (not `*_url`) so `export.py`'s suffix rule does not silently drop the key |

### 3.2 Explicitly excluded, with reasons

| Excluded | Reason |
|---|---|
| `stat` counters (view/like/coin/favorite) | **Time-varying.** Following **D11** (metadata is refreshed on recollect, not frozen), freezing them would need a timestamped append-only child table that this iteration does not create — and no reader asks for one. Horizon 2026-09-26: the value at an unknown past moment is worse than an absent field, which is why this stays excluded rather than deferred |
| `rights` (18 keys) | Permission flags that describe the platform, not the work; no reader in this archive consumes them |
| `dimension` (width/height/rotate) | Marginal for an audio/transcript archive; reachable later from the same response at zero cost if a reader appears |
| `first_frame`, `vid`, `weblink` | Part-level presentation trivia; `first_frame` is a storyboard URL that `export` would redact anyway |
| Resolving `tid` → `tname` | Upstream returned `tname`/`tname_v2` as **empty strings** for every video probed on 2026-09-26, and the pin's local `data/video_zone.json` table has no entry for the observed `tid_v2` values. A category-name mapping would be invented, not measured |
| `desc_v2`, `dynamic`, `argue_info` | Redundant or empty on the observed corpus |

### 3.3 The risk-control constraint

Extra calls are neither free nor safe. On 2026-09-26, from this host:

| Endpoint | Result |
|---|---|
| `/x/web-interface/view` | `code 0`, 45 keys, unsigned |
| `/x/web-interface/view/detail/tag` | `code 0`, 2-6 tags, unsigned |
| `/x/player/pagelist` | `code 0`, unsigned |
| `/x/player/wbi/v2` and `/x/player/v2` | `code 0`, 48 keys |
| `/x/space/wbi/arc/search` (via the pinned package) | `code 0` twice, then **HTTP 412** |
| `/x/web-interface/wbi/view/detail` | `code 0` twice, then **`-352 风控校验失败`** |
| `/x/web-interface/archive/stat` | HTML 404 challenge page |

**Rules:** (a) prefer fields already present in a response the pipeline fetches today; (b) a new call must be
justified individually and cached per video, never per part; (c) a risk-controlled endpoint must never become
a hard dependency of the ingest path — a `-352`/`412` on tags degrades to "no tags recorded", it does not
fail the run; (d) credentials are never added to a call that answers anonymously today.

## 4. Identity and formatting rules inherited from the shipped code

- **Tag identity** is `(bvid, tag_id)`. `tag_name` is a display label and may be renamed upstream; the id is
  the identity. A re-fetch replaces the video's set rather than accumulating versions.
- **`video_title` is additive.** The frontmatter key `title` keeps meaning the *part* title. Redefining an
  existing published key is a silent format change and is forbidden; a sibling key is honest.
- **The frontmatter key set is pinned** by `test_write_archive_publishes_the_exact_asr_key_set`
  (`tests/test_archive_md.py:297-349`, offsets as of the `video_title` revision `2696711`) as an **exact
  ordered list of 25 keys**: the literal at `:335-342`, `assert len(front) == 25` at `:343`, and 15 of them
  `asr_*` at `:344`. The key that revision added is `video_title` — 3rd in that ordered literal, directly
  beside `title` — the **video's** own title, a sibling of `title`, which keeps meaning the **part** title
  (**compass D4/D5**). The list read 24 before that revision (corrected 2026-09-27, residual R3). A new key is
  a deliberate format revision: update the assertion in the same commit and say so in the commit body.
- **Export redaction is separate from storage, and the separation is a decision (compass D12).** In
  `src/bili_asr/export.py`, `_is_sensitive_key` (`:85-98`) drops every key in `SENSITIVE_EXPORT_KEYS`
  (`:37-64`, naming `cover_url` exactly at `:48`), every key ending in `_SENSITIVE_KEY_SUFFIXES`
  (`:66-73`), and every key ending in `url` (`:94`); `_sanitize_value` (`:174-177`) replaces every value
  starting `http(s)://` with `[redacted]`. Storage decisions therefore do not change export output, and a
  stored `pic` is invisible in an export **by design** — the ruling, not a gap. Making a cover visible in an
  export is a **new** decision (an explicit allow-list entry with its own trigger), not a relaxation of this
  rule and not an implementation detail of this iteration.

## 5. Verification obligations

- The gateway's call allow-list (`DOCUMENTED_METADATA_CALLS`,
  `tests/fixtures/fake_bilibili_gateway.py:138-144`) is **exact**: a new call is added to it and to its pin
  (`tests/test_bilibili_api_gateway.py:2272-2278`) in the same commit, and the guard must still reject a call
  outside the set (`assert_only_documented_metadata_calls`, `:821-827`).
- The per-video caching rule has a test with a **multi-part** video: one tag call for three parts.
- No test may perform a network call; the fake upstream is the only channel.
