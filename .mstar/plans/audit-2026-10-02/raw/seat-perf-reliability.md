# Raw findings — seat `seat-perf-reliability` (performance + reliability/concurrency)

Audit of `bilibili-asr-archive` @ `1e756df` (delta `ff39fd0..1e756df`), read-only.
Playbook read: `…/mstar-audit/references/audit-playbook.md` — § *3. Performance*, § *1. Correctness /
reliability half*, and **Finding format** (read first, format followed below).
Every anchor below was opened by this seat; mechanism stated, no unmeasured percentages.
Already-registered ids are cited, never re-reported. Category codes match the playbook.

---

### [BUG-01] `ManifestStore._replay_latest` splits the journal with `str.splitlines()`, so one U+2028/U+2029/U+0085 inside a row truncates the ledger replay — and the next snapshot rewrite loses every later row

- **Evidence**: `src/bili_asr/manifest.py:253` — `for line in raw.decode("utf-8", errors="replace").splitlines():` inside `_replay_latest()`, with `except ValueError: break` at `:258-261` (a split fragment is invalid JSON → `break` drops the whole remainder of the journal). The writer is `ensure_ascii=False` (`src/bili_asr/persistence.py:114` `_json_line`, and `manifest.py:367` for the snapshot), so U+2028/U+2029/U+0085 are emitted raw inside string values (titles, `video_title`, part titles, paths). The sibling fix for exactly this defect class is already in the same delta: `src/bili_asr/coordinator.py:305-315` documents that the attempt-ledger tail must be split on `"\n"` only, "never `str.splitlines()`, which also breaks on U+2028/U+2029/U+0085 — legal inside a JSON string and written raw by this repo's own writer"; `manifest.py` was not given the same treatment. Read side that is *not* affected (proving the class, not the read mode, is the problem): `_read_latest()` iterates the snapshot in text mode (`manifest.py:190-197`), and `sidecar_projection.iter_jsonl_records` reads by `readline` (`sidecar_projection.py:95-118`).
- **Impact**: A single such character in any journaled row makes `ManifestStore.load()`/`upsert()`'s in-memory view stop at that row for the lifetime of the store instance — every later transition (including `archived`) is invisible, and `_refresh_if_stale_locked` re-derives the same truncated view on every later upsert (the signature matches, the replay result does not change). Worse, the truncated view is what `save()`/`compact()`/`migrate_legacy_rows()`/`_maybe_compact_locked` write back with `_replace_snapshot()` (`manifest.py:312, 392, 404, 597`), so the rows after the break are **durably deleted** on the next compaction. Two readers of the same ledger then disagree: `project_manifest_records` (verify/coverage/status) replays by newline and still sees those rows (`sidecar_projection.py:193-218, 267-289`). The ledger is the resumable SSOT, so the loss is silent — a re-run reprocesses rows already archived, and the compaction that loses them prints nothing.
- **Effort**: S — one split change plus a regression test with a U+2028-bearing row.
- **Risk**: LOW — same semantics as the already-fixed attempt-ledger split; the failure mode is strictly a strict-superset of lines.
- **Confidence**: HIGH on the mechanism (read both replays and both writers); MED on triggering prevalence (a title/part title carrying U+2028 is rare but not impossible for Bilibili titles, and the row set is corpus-wide).
- **Fix sketch**: Split the journal bytes on `b"\n"` (or `text.split("\n")`) exactly as `AttemptLedger._replay_lines` does; keep "break on the first invalid record" as the torn-tail rule. Add a test journaling a row whose title contains U+2028 and assert the later row still replays and survives a `save()`.

---

### [BUG-02] `QueueSource.ensure_asr_run` mints `run_id = f"{command}-{int(time.time())}"` against a PRIMARY KEY and swallows the collision, silently disabling every transcript write-back in that invocation

- **Evidence**: `src/bili_asr/services/queue_source.py:140-157` — `now = int(_time.time()); run_id = f"{command}-{now}"`, then `start_acquisition_run(...)` wrapped in `except Exception: self.asr_run_id = None` (`:155-157`). `acquisition_runs.run_id` is `TEXT PRIMARY KEY` with no reuse (`src/bili_asr/storage/schema-transcripts.sql:50-51`) and `start_acquisition_run` raises `sqlite3.IntegrityError` on a duplicate (`src/bili_asr/storage/database.py:931-961`). Callers key *every* per-part write-back on that id: `coordinator.py:750, 782` (`_record_subtitle_transcript` / `_record_asr_transcript`), `cli/asr.py:287-299`, `cli/pilot.py:592-611`.
- **Impact**: Two invocations of the same command inside one wall-clock second (a fast-failing retry, a scripted loop, two shells, or `pilot`'s own second connection after `run` just ran) make the second `start_acquisition_run` collide; the `Broad except` converts it into `asr_run_id = None`, and the entire run's `transcripts` rows are skipped **silently** — exactly the R14-class gap (`v_missing_transcript` never drains) the write-back was landed to close, now re-entered at one-second granularity instead of never. The operator sees a successful archive; only the store's gap views stay stuck.
- **Effort**: XS–S — make the id unique (monotonic suffix / uuid4 / `INSERT OR IGNORE` + read-back) or retry with a fresh second; a test that two sources in the same second each record a transcript.
- **Risk**: LOW — id-format change only; nothing parses the id but the store itself.
- **Confidence**: HIGH (schema PK + swallow both read); the frequency claim (same-command retry within a second) is an operational shape, not a measurement.
- **Fix sketch**: Derive the id from a monotonic source (`f"{command}-{time_ns}"`, or `uuid4().hex`) or attempt `start_acquisition_run` with an id suffix bump on `IntegrityError` before giving up; never let a swallowed failure silently disable write-backs without a stderr line.

---

### [PERF-01] The append journal never compacts on any in-repo path, so every fresh process and every projection re-parses an ever-growing snapshot+journal

- **Evidence**: `src/bili_asr/manifest.py:51-54` — `_JOURNAL_COMPACT_THRESHOLD = 256`, `_JOURNAL_WRAP_BYTES_FACTOR = 2`; `:295-315` `_maybe_compact_locked` requires **both** `self._appends_since_compact >= 256` (a *per-instance* counter reset at construction, `:128`) **and** `journal_bytes >= max(1, 2 * snapshot_bytes)`. Grep of the whole tree: **no production caller invokes `save()` or `compact()`** (`grep -rnE "\.save\(|\.compact\(" src/` → no hits; only `tests/` call them). Readers that pay the full replay: `ManifestStore.load()` → `_replay_latest()` (`:222-266`, reads and validates every snapshot row **and** every journal row), `sidecar_projection.replay_journal_records` (`sidecar_projection.py:193-218`, used by `project_manifest_records` → `integrity`, `coverage_report`, `cli/status_cmd`), and `SearchIndex.is_stale` (`search_index.py:527-533`).
- **Mechanism** (no percentage): once a corpus-sized snapshot exists (`snapshot_bytes ≈ 0.5 MB` for ~1730 rows × ~300 B), a compaction needs the journal to exceed ~1 MB ≈ **~3400 full-row appends inside one process instance**, while a status row is rewritten on every transition (pending→meta_ok→needs_audio→audio_ok→archived ≈ 3-5 appends per archived row). Normal invocation shapes (`run --limit N`, `asr`, `pilot`) append far fewer than 256 rows per process, so the per-instance counter resets before the byte clause can ever be evaluated true; the journal is therefore only ever folded by a `save()`/`compact()` that nothing calls. Cost per fresh process = O(snapshot bytes + journal bytes) parse+validate, and the journal grows monotonically with every corpus pass; the on-disk ledger's read cost is unbounded in the number of transitions ever recorded, not in the corpus size.
- **Impact**: Every CLI invocation (`run`, `asr`, `pilot`, `search` via `is_stale`, `verify`/`coverage`/`status` via the projection) pays a full ledger parse; on a long-lived archive the journal becomes the dominant artifact of `manifest/`, and the deterministic snapshot — the thing designed to bound the read — is never refreshed. The wrap-bytes clause also means the journal can hold more rows than the snapshot while every reader reads both.
- **Effort**: S–M — a bytes-only trigger (e.g. compact when `journal_bytes >= snapshot_bytes` even if the instance appended once), or a reachable `compact` command, plus a test asserting the journal shrinks after N cross-process appends.
- **Risk**: MED — compaction rewrites the snapshot and unlinks the journal while readers may be between their own stat and read (`_replay_latest` already tolerates a missing journal; a reader that opened the journal first is fine, but the unlink/replace interleaving deserves the existing crash-window tests).
- **Confidence**: HIGH (thresholds, counter scope, and the absence of callers are all read, not inferred).
- **Fix sketch**: Drop the per-instance counter from the gate and trigger on journal size relative to the snapshot (compaction is idempotent and already lock-held); alternatively expose `ManifestStore.compact()` through a maintenance command so an operator can fold the journal after a campaign. Note the existing guard `if not current:` must keep the journal intact when the snapshot is absent (adjacent to registered `I-000138`).

---

### [PERF-02] `SearchIndex.is_stale()` repays the whole ledger replay plus per-row filesystem probes on every `search` invocation

- **Evidence**: `src/bili_asr/search_index.py:527-533` — `store.load()` (full snapshot+journal replay, see PERF-01) is executed inside `is_stale()` whenever the caller passes no manifest; `:539-544` — `completed_count = sum(1 for e in entries.values() if self._is_indexable(e))`; `_is_indexable` (`:547-586`) runs `os.path.isfile` over up to 5 relative paths × every `artifact_roots.read_bases()` (`:574-586`) for any completed-status row that carries no `srt_path/txt_path/md_path/raw_path`. Call site: `cli/search.py:151` passes `auto_build=True` (the default, `search_index.py:125`), and `_execute_query` calls `is_stale()` at `:737`.
- **Impact**: A search that hits a fresh index still pays (a) the full ledger parse including the growing journal (PERF-01) and (b) a filesystem probe of up to `5 × read_bases` `stat` calls for every pathless archived row — on the documented WebDAV artifact root those are network round trips per row per query. The mtime guard above (`:511-525`) cannot early-exit for a same-count change, so the count path always runs; only an mtime-newer-than-DB exit is cheap. Cost scales with corpus size per query, not per index rebuild.
- **Effort**: S — cheap guard: skip the per-entry probe when the index's stamped part set already covers the row (the index can answer "indexed" by `work_id`), or bound the probe to rows the DB does not hold.
- **Risk**: MED — the count check is the freshness contract; a too-eager skip can serve a stale index (the rebuild decision must stay count-based for rows that genuinely have no stamp).
- **Confidence**: MED-HIGH — the replay and the count loop are read; how often archived rows are pathless in the live corpus is not verified here, so the probe cost is conditional while the replay cost is unconditional.
- **Fix sketch**: Have `is_stale` compare `work_id`s the DB holds against the completed set instead of re-probing the filesystem, or memoize the probe result per path per process. Keep the un-stamped fallback for rows the index cannot know.

---

### [BUG-03] `set_pacing_floor()` is dead in `src/`, so every small `fetch-meta` selection pays the full 0.8–1.6 s pacing sleep per upstream call with no opt-out

- **Evidence**: `src/bili_asr/sources/bilibili_api_gateway.py:763-778` defines `set_pacing_floor`, `:794-796` gates `_pace()` on it, and `:761` defaults it to `None` ("always pace"). Grep across the tree: the only callers are `tests/test_bilibili_api_gateway.py:1530,1542,1551,1554,1555,1569` — **no production caller**. The docstring at `:765-771` states "the enumeration entry point lowers it per run", but `services/metadata_ingest.py` (the enumeration caller of the three getters at `:358, 370, 507`) never calls it.
- **Impact**: The three per-row getters await `_pace()` (`:825, 843, 899`), each sleeping `0.8 + U(0,1)×0.8` s. For the intended small selections the delta's own contract says pacing should be skipped, but the knob has no wiring, so a single-bvid `fetch-meta` pays ~2.4–4.8 s of sleep per video and any page-driven run pays the full ~90 sleeps — the cost the floor was added to avoid. Asymmetric with the tag leg is gone (all three pace), which is good; what remains is a documented-but-absent opt-out.
- **Effort**: XS — call `set_pacing_floor(expected_rows)` from the enumeration entry point, or delete the dead seam and its docstring claim.
- **Risk**: LOW — no behavior change unless wired; wiring a too-low floor on a big run would remove the 412 protection, so the floor must be set from the run's real expected row count.
- **Confidence**: HIGH (grep evidence: definition + tests only).
- **Fix sketch**: In `metadata_ingest`, compute the run's expected rows (the same count the run's limit/selector resolves) and call `gateway.set_pacing_floor(expected_rows)` before the page loop; keep `None` as the conservative default. (Registered `I-000053` tracks the tag leg; `I-000141` tracks the sleep-in-async class; this finding is the unwired seam, not a re-report.)

---

### [BUG-04] `ManifestStore.save()` unlinks the journal *before* rewriting the snapshot — crash window loses every journaled row; `compact()`/`migrate_legacy_rows()` use the opposite order

- **Evidence**: `src/bili_asr/manifest.py:380-392` — under `_manifest_lock`: `current, _ = self._replay_latest()`, then `self._remove_journal()` (an `unlink` + directory `fsync`, `:317-326`), and only afterwards `if not current: … return` / `self._replace_snapshot(current)` (temp write + `os.replace`, `:328-361`). Compare `compact()` `:396-407` (`_replace_snapshot` **then** `_remove_journal`) and `migrate_legacy_rows()` `:597-603` (same order) — `save()` is the only inverted path in the file.
- **Impact**: A crash, SIGKILL, or raised `OSError` (ENOSPC on the temp write) between the journal unlink and the `os.replace` loses all rows that lived only in the journal (they were in `current`, an in-memory dict that dies with the process), while the old snapshot stays in place — the ledger silently rolls back to its pre-transition state. Durability is the contract `_append_record` fsyncs for, so the window is a real (if narrow) data-loss surface. Reachability is currently out-of-tree: no `src/` caller invokes `save()` (see PERF-01's grep; only `tests/` do), so this is a latent defect in newly landed code rather than a live one. Not a re-report of registered `I-000138` (that row concerns `compact()` with an absent snapshot; this is `save()`'s ordering window).
- **Effort**: XS — reorder two calls (write snapshot first, unlink journal after success).
- **Risk**: LOW — the reorder makes `save()` match its two siblings; the only care is keeping the empty-`current` early return from deleting a journal it did not fold.
- **Confidence**: HIGH (all three orderings read).
- **Fix sketch**: Move `_remove_journal()` after `_replace_snapshot()` in `save()`, matching `compact()`; when `current` is empty, leave both artifacts untouched. Add a test that a failure between write and unlink leaves the journal recoverable.

---

### [PERF-03] `search_index._published_md_candidates` builds an unchunked `NOT IN (…)` list, unlike its own batched siblings

- **Evidence**: `src/bili_asr/search_index.py:1320-1337` — `stamped_clause = "AND vp.video_part_id NOT IN (" + ",".join("?" for _ in exclude) + ") "` with `params.extend(sorted(exclude))`; one bound variable per stamped md part, with no chunking. The same file chunks the analogous reads at `:1595-1640` (`_IN_CHUNK = 900`, `_chunked`) because "the list never approaches SQLite's variable ceiling" (`:1588-1590`). `stamped_part_ids` is built from the whole index at `:1418-1424`, so the list equals the number of md-sourced parts.
- **Impact**: Past SQLite's bound-variable ceiling (~32766 by default, ~250000 on the build the file names) the build's candidate query raises `sqlite3.OperationalError`, which the build path does not translate into a friendly error — the index build fails at corpus sizes far beyond today's 1730 rows (roughly >32k published-md parts), and the failure mode is a raw SQLite error mid-build. Bounds-covering defect class: the final operation (the candidate SELECT) has no owner enforcing the bound, while the neighbouring reads do.
- **Effort**: XS — reuse `self._chunked(...)` for the exclusion list (or push the anti-join against the index table instead of a parameter list).
- **Risk**: LOW — chunking changes only how the same predicate is issued; the ordered candidate semantics stay.
- **Confidence**: HIGH (both shapes read; ceiling value is the file's own citation).
- **Fix sketch**: Issue the candidate query per exclusion chunk and merge/dedupe by `video_part_id`, or derive the exclusion set from the stored index rows in SQL rather than binding it.

---

## Checked and explicitly **not** findings (delta surfaces this seat probed)

- `AttemptLedger` size-fingerprint tail replay is sound: the fingerprint is captured before the seeding read (`coordinator.py:197-206`), the tail is realigned to a `\n` boundary with a bounded window (`:296-340`), and it splits on `"\n"` only — deliberately not `splitlines()` (`:305-315`). The `_replay_lines` strict/non-strict split and the re-validated malformed verdict (`:352-375`) preserve fail-closed numbering.
- `ManifestStore._append_record` rolls the in-memory view back to the replayed ledger when the append raises (`manifest.py:452-461`); `_refresh_if_stale_locked` stat-checks the journal under the lock before trusting `_entries` (`:209-220`). The cross-process upsert invariant is handled for the append path; only the `save()` ordering above is off.
- `search_blocks` batching is genuine: one `_snippets_for_hits` read for all hit keys and one `_titles_for_bvids` read bounded to hit bvids, both chunked (`search_index.py:1595-1640`); the prior N+1 (`I-000127`) is addressed in this delta and is cited, not re-reported.
- `RunCoordinator`'s write-back source is opened once per batch, closed on every exit path (`coordinator.py:680-712`, `:1204`), and the write-back helpers swallow exactly the store-failure classes they document (`queue_source.py:385, 447`); the ASR-arm write-back runs after `_mark_archived` (`coordinator.py:990`), so a store failure cannot un-archive a row.
- `metadata_ingest`'s page loop already dedupes detail/parts/tags per distinct video (`metadata_ingest.py:333-372`); the per-video calls are the intended sequential shape (`sequential-no-daemon`, by design).

## Leads (not findings — no plan claimed)

- `_probe_videos_readable` (`search_index.py:1595-1608`) does `SELECT bvid, title FROM videos` + `fetchall()` on **every** zero-hit query to prove readability — O(corpus) for a result that is empty by definition. Cheap today (~1.7k rows); worth folding into the next search-index touch.
- `acquisition_runs` rows created by `ensure_asr_run` are never finished: `finish_acquisition_run` has no caller on the ASR path (`grep` → only `services/subtitle_ingest.py:359, 384`), so each `asr`/`pilot`/`run` invocation leaves a run row with `finished_at`/`outcome` NULL. Volume is one row per invocation (negligible); the derived run-outcome contract never applies to these runs. Related to registered `I-000084` (attempt-history growth), distinct in kind.
- `search_index._IN_CHUNK` boundary behaviour has no test pin (registered as `I-000158` — cited, not re-reported); the new `_published_md_candidates` parameter list (PERF-03) is the same class and should share that pin.
- `coverage_report._read_manifest` (`coverage_report.py:294-330`) still reads `manifest.jsonl` directly without the journal replay — zero call sites today (registered `I-000019` tracks the latent second judgement); if it ever gains a caller it would read a stale ledger by construction.

## Truncated coverage

- Did not examine: `asr.py` two-pass runner internals beyond `two_pass_transcribe` (`asr.py:1383-1405`); `storage/models.py` validation costs; `services/subtitle_ingest.py` pacing/runs; `cli/publish.py`, `export.py`, `scheduler.py`, `campaign.py` beyond greps; the full test suite beyond `tests/test_persistence_scale.py`'s surface; `.venv/`, `docs/`, `notes/`.
- File budget was exceeded (≈20 partial file reads vs the ≤12 named): triage was done with `git diff`/`grep`, and only cited ranges were opened, but the count is over budget and is declared rather than hidden.
