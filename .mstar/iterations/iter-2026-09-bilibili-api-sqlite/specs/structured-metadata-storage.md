# Structured Metadata Storage Specification

## Intent

Create a fresh SQLite-backed metadata store for the Bilibili ASR archive. The
store is the source of truth for normalized user, video, part, and ingestion
state. This iteration does not read or migrate the previous JSONL archive.

## 3NF contract

The base schema must satisfy 1NF, 2NF, and 3NF:

- Every column is scalar; lists and complete API documents are not stored in
  entity rows.
- Every non-key attribute depends on the whole key of its table.
- No non-key attribute depends on another non-key attribute. Derived values such
  as `work_id`, part count, and run counts are views or application projections.

## Canonical metadata retention

The database stores stable identifiers and processing facts plus the current
display labels needed to operate the archive. It does **not** store historical
snapshots. When metadata is re-ingested:

- **Stable identifiers remain unchanged**: `bvid`, `aid`, `cid`, `mid`, `pubdate`
  (published timestamp), `page_index`.
- **Display labels are overwritten**: `title` (video/part), `display_name` (user).
  These are operational values, not historical records.
- **Mutable upstream fields are not retained**: View counts, likes, comments,
  descriptions, and other changing statistics are not stored.
- **No claim of immutability**: Display labels may change upstream; the database
  reflects the latest seen value, not a promise that the upstream value is stable.

This is operational metadata, not a historical metadata warehouse.

## Tables

### `bilibili_users`

| Column | Type | Constraint | Meaning |
|---|---|---|---|
| `mid` | INTEGER | PK | Bilibili user identity |
| `display_name` | TEXT | NOT NULL | Latest display name, overwritten on upsert; no history |
| `created_at` | INTEGER | NOT NULL | Local first-seen time |
| `updated_at` | INTEGER | NOT NULL | Local last-seen time |

Functional dependency: `mid -> display_name, created_at, updated_at`.

### `videos`

| Column | Type | Constraint | Meaning |
|---|---|---|---|
| `bvid` | TEXT | PK | Stable Bilibili video identity |
| `aid` | INTEGER | UNIQUE, nullable | Numeric video identity when supplied |
| `mid` | INTEGER | FK to `bilibili_users`, NOT NULL | Owner identity |
| `title` | TEXT | NOT NULL | Latest canonical title; no title history |
| `pubdate` | INTEGER | NOT NULL | Published timestamp |
| `created_at` | INTEGER | NOT NULL | Local first-seen time |
| `updated_at` | INTEGER | NOT NULL | Local last-seen time |

Functional dependency: `bvid -> aid, mid, title, pubdate, created_at, updated_at`.
The owner name is not duplicated here; it is reached through `mid`.

### `video_parts`

| Column | Type | Constraint | Meaning |
|---|---|---|---|
| `video_part_id` | INTEGER | PK | Local part identity |
| `bvid` | TEXT | FK to `videos`, NOT NULL | Parent video |
| `page_index` | INTEGER | NOT NULL, >= 0 | Zero-based page index (normalized from Bilibili one-based page) |
| `cid` | INTEGER | NOT NULL, > 0 | Bilibili content ID |
| `title` | TEXT | NOT NULL | Latest part title |
| `duration_ms` | INTEGER | NOT NULL, > 0 | Part duration in milliseconds (converted from seconds using `floor(seconds * 1000)`) |
| `processing_status` | TEXT | NOT NULL | `discovered`, `metadata_collected`, or `gone` |
| `created_at` | INTEGER | NOT NULL | Local first-seen time |
| `updated_at` | INTEGER | NOT NULL | Local last-seen time |

Candidate key: `(bvid, page_index)`; unique constraint required. Functional
dependencies: `video_part_id -> bvid, page_index, cid, title, duration_ms,
processing_status, created_at, updated_at` and `(bvid, page_index) -> video_part_id,
cid, title, duration_ms, processing_status, created_at, updated_at`.
`work_id` is computed as `bvid || ':p' || page_index` in a view and is not stored.

**Normalization note**: `page_index` is the zero-based normalized form stored in this
table. The ingestion layer tracks one-based `page_number` values as requested from
the API; conversion happens at the gateway boundary.

### `ingestion_runs`

| Column | Type | Constraint | Meaning |
|---|---|---|---|
| `run_id` | TEXT | PK | One metadata collection run |
| `mid` | INTEGER | FK to `bilibili_users`, NOT NULL | Collection target |
| `source_package` | TEXT | NOT NULL | `bilibili-api-python` |
| `source_version` | TEXT | NOT NULL | Locked package version |
| `requested_start_page` | INTEGER | NOT NULL, >= 1 | Initial page |
| `requested_page_limit` | INTEGER | nullable, > 0 | Explicit smoke/batch bound |
| `started_at` | INTEGER | NOT NULL | Run start |
| `finished_at` | INTEGER | nullable | Run finish |
| `outcome` | TEXT | NOT NULL | `running`, `complete`, `limited`, `risk_interrupted`, `failed` |

All columns describe one run; no video counts are stored because they are
aggregated from `ingestion_discoveries`.

### `ingestion_cursors`

| Column | Type | Constraint | Meaning |
|---|---|---|---|
| `mid` | INTEGER | PK/FK to `bilibili_users` | Cursor owner |
| `next_page` | INTEGER | NOT NULL, >= 1 | Next page to request |
| `observed_total` | INTEGER | nullable, >= 0 | Latest API total |
| `state` | TEXT | NOT NULL | `ready`, `complete`, `limited`, `risk_interrupted` |
| `last_error_code` | TEXT | nullable | Bounded scalar code only |
| `updated_at` | INTEGER | NOT NULL | Cursor update time |

Functional dependency: `mid -> next_page, observed_total, state, last_error_code,
updated_at`.

### `ingestion_pages`

| Column | Type | Constraint | Meaning |
|---|---|---|---|
| `run_id` | TEXT | NOT NULL, FK to `ingestion_runs` | Parent run |
| `page_number` | INTEGER | NOT NULL, >= 1 | Requested page (one-based, as sent to Bilibili API) |
| `outcome` | TEXT | NOT NULL, CHECK | `ok`, `empty`, `risk_interrupted`, `failed` |
| `error_code` | TEXT | nullable | Bounded scalar code only |
| `started_at` | INTEGER | NOT NULL | Page start |
| `finished_at` | INTEGER | NOT NULL | Page finish |

Primary key: `(run_id, page_number)`. Functional dependencies: `(run_id, page_number)
-> outcome, error_code, started_at, finished_at`. Video counts per page are derived
from `ingestion_discoveries`, not duplicated here.

**Normalization note**: `page_number` here is one-based (API request convention),
while `video_parts.page_index` is zero-based (normalized storage). This dual
convention separates ingestion evidence (what was requested) from entity identity
(normalized part index).

### `ingestion_discoveries`

| Column | Type | Constraint | Meaning |
|---|---|---|---|
| `run_id` | TEXT | NOT NULL, FK to `ingestion_runs` | Parent run |
| `page_number` | INTEGER | NOT NULL, >= 1 | Source page |
| `bvid` | TEXT | NOT NULL, FK to `videos` | Discovered video |
| `source_position` | INTEGER | nullable, >= 0 | Position returned on that page |
| `discovered_at` | INTEGER | NOT NULL | Local observation time |

Primary key: `(run_id, page_number, bvid)`; this is a relationship table and
all attributes describe that discovery relationship.

## Future structured object boundaries

The initial schema must include these empty, schema-only reservation tables because
later subtitle/audio plans depend on their keys. They must not be populated or
queried as active media/transcript state by this metadata plan:

### `audio_objects`
- `audio_id` INTEGER PK
- `sha256` TEXT NOT NULL UNIQUE
- `byte_size` INTEGER NOT NULL
- `format` TEXT NOT NULL
- `duration_ms` INTEGER NOT NULL
- `storage_key` TEXT NOT NULL UNIQUE
- `created_at` INTEGER NOT NULL

### `part_audio_objects`
- `video_part_id` INTEGER NOT NULL, FK to `video_parts`
- `audio_id` INTEGER NOT NULL, FK to `audio_objects`
- `acquired_at` INTEGER NOT NULL
- `acquisition_source` TEXT NOT NULL
- Primary key: `(video_part_id, audio_id)`

### `asr_models`
- `model_id` INTEGER PK
- `model_name` TEXT NOT NULL
- `revision` TEXT NOT NULL
- `created_at` INTEGER NOT NULL
- Unique: `(model_name, revision)`

### `transcripts`
- `transcript_id` INTEGER PK
- `video_part_id` INTEGER NOT NULL, FK to `video_parts`
- `source_kind` TEXT NOT NULL (`subtitle-ai`, `subtitle-cc`, `asr-local`)
- `model_id` INTEGER nullable, FK to `asr_models`
- `version` INTEGER NOT NULL
- `created_at` INTEGER NOT NULL
- Unique: `(video_part_id, source_kind, version)`

### `transcript_segments`
- `transcript_id` INTEGER NOT NULL, FK to `transcripts`
- `ordinal` INTEGER NOT NULL
- `start_ms` INTEGER NOT NULL
- `end_ms` INTEGER NOT NULL
- `text` TEXT NOT NULL
- Primary key: `(transcript_id, ordinal)`

Audio bytes remain external immutable objects referenced by `storage_key`; text
segments are relational rows. SRT/TXT/MD are derived projections and are not
facts in the metadata plan.

**Foreign-key contract**: All FK relationships above must be explicitly declared with
`ON DELETE RESTRICT` to prevent orphaned media/transcript references. Future plans
must populate these tables through explicit transactions that verify parent existence.

## Views

### `v_video_parts`
Computes `work_id` and joins user/video/part metadata:
```sql
SELECT 
  vp.video_part_id,
  vp.bvid || ':p' || vp.page_index AS work_id,
  u.display_name AS user_name,
  v.title AS video_title,
  vp.page_index,
  vp.cid,
  vp.title AS part_title,
  vp.duration_ms,
  vp.processing_status,
  vp.created_at,
  vp.updated_at
FROM video_parts vp
JOIN videos v ON vp.bvid = v.bvid
JOIN bilibili_users u ON v.mid = u.mid
```

### `v_ingestion_run_stats`
Derives run/page/video counts from normalized base tables:
```sql
SELECT 
  ir.run_id,
  ir.mid,
  ir.started_at,
  ir.finished_at,
  ir.outcome,
  COUNT(DISTINCT ip.page_number) AS page_count,
  COUNT(DISTINCT id.bvid) AS video_count
FROM ingestion_runs ir
LEFT JOIN ingestion_pages ip ON ir.run_id = ip.run_id
LEFT JOIN ingestion_discoveries id ON ir.run_id = id.run_id
GROUP BY ir.run_id
```

### `v_pending_metadata`
Selects parts needing further processing:
```sql
SELECT 
  vp.video_part_id,
  vp.bvid || ':p' || vp.page_index AS work_id,
  vp.bvid,
  vp.page_index,
  vp.processing_status
FROM video_parts vp
WHERE vp.processing_status = 'discovered'
```

**Normalization note**: All derived values (`work_id`, aggregates, joined display
names) appear only in views, never in base tables.

## Transaction and integrity rules

- Enable `PRAGMA foreign_keys = ON` for every connection.
- Use explicit transactions for one page with this order:
  1. Upsert `bilibili_users` (ensures FK parent exists)
  2. Upsert `videos` (ensures FK parent exists)
  3. Upsert each `video_parts` row (FK parent now guaranteed)
  4. Insert `ingestion_discoveries` rows (FK parents now guaranteed)
  5. Update `ingestion_cursors` (only on success)
  6. Record `ingestion_pages` outcome
  7. Commit transaction atomically
- On any failure before commit: rollback entire transaction, leaving prior cursor
  and all prior state unchanged.
- Repeating the same page is idempotent through primary/unique keys and an
  upsert that changes only current canonical fields (titles, display names).
- Error fields are bounded scalar codes; no cookies, URLs, raw JSON, or tracebacks.
- A fresh database is created by schema initialization; no migration path is
  part of this iteration.
- Foreign keys must be declared with `ON DELETE RESTRICT` to prevent accidental
  orphaning of dependent records.

## Out of scope

No subtitle, audio, ASR, export, vector, or historical metadata snapshot write
is implemented by this specification.

## References

- User-supplied API docs: https://nemo2011.github.io/bilibili-api/#/modules/user
- Package: https://pypi.org/project/bilibili-api-python/
- Primary plan: `.mstar/plans/20260909-structured-metadata-schema.md`
- Follow-up gateway plan: `.mstar/plans/20260909-bilibili-api-ingestion.md`

## Status

Iteration-scoped draft; becomes locked after Phase 1 review chain and PM lock.
