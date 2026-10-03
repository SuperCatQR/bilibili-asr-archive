# Raw findings — seat t1 (correctness/security), audit-2026-10-02 run 2

Scope: delta `ff39fd0..1e756df` (50 files, +4279/-569) + the 5 HIGH open issues.
Method files read: `mstar-audit/references/audit-playbook.md` (§1, §2, § Finding format) and
`mstar-audit/references/security-review.md` (§2 exploitability bar, §4 input triage, §5 FP table,
§6 secret discipline, §7 data-flow). Read-only: no source file touched.

Evidence base (files opened/read in full or in the cited regions):
`coordinator.py`, `manifest.py`, `search_index.py`, `services/queue_source.py`, `storage/database.py`,
`storage/models.py`, `sidecar_projection.py`, `sources/bilibili_api_gateway.py`, `integrity.py`,
`page_identity.py`, `quality.py`, `cues.py`, `cli/pilot.py`, `cli/asr.py`, `persistence.py`,
`cli/meta.py`, `archive.py`.

---

### [BUG-01] Subtitle-arm write-back failure deletes a correctly archived bundle's `archive: ok` attempt

- **Evidence**: `bilibili-asr-archive/src/bili_asr/coordinator.py:850` — `self._record_subtitle_transcript(...)`
  is called **inside** the `try:` that begins at `:845`, before the `archive: ok` ledger record, while the
  sibling ASR write-back is deliberately outside its guard (`:990`, in `_stage_asr_archive`, called from
  `:1071`). The pair sits in the shared envelope `bundle complete → write-back → archive: ok`, whose
  `except Exception as exc: self._record("archive", work_id, "failed", …); raise` is at `:853-858`.
- **Impact**: Two layers of protection exist for a store failure — `record_caption_transcript`'s
  `except (_sqlite3.Error, OSError, ValueError, TypeError, KeyError)` at
  `services/queue_source.py:447`, and nothing else. The cue conversion is **not** inside that boundary:
  `segments=_caption_transcript_segments(segments)` is an *argument expression* evaluated in
  `_record_subtitle_transcript`'s own frame (`coordinator.py:1365-1383`, the `float(cue.get("start", 0.0))
  * 1000` at `:1381-1382`), i.e. before `qs.record_caption_transcript` is entered, so its `try` cannot see
  a `TypeError`/`ValueError` from a non-numeric cue time. That exception reaches the caller's `try` at
  `:845`, which records `archive: failed` for a row whose four artifacts are already published by
  `write_archive`, and re-raises. `_mark_archived` (`:860`) is skipped, so the manifest row never becomes
  `archived`: the operator sees a failure for a complete archive and a rerun republishes the same bundle.
  The helper's own docstring states the opposite ("One cue that cannot convert … fails this part's
  write-back only — the helper is called inside the best-effort boundary, so the archive on disk stands"),
  so the code contradicts its stated contract; the sibling ASR route has the call outside its guard
  (`:990`) and does not have this hole.
- **Effort**: XS (move the call after the `_record("archive", … "ok")` block, beside `_mark_archived`).
- **Risk**: LOW — the write-back is already independently best-effort and order-independent of the ledger
  writes; moving it strictly reduces what can fail the row.
- **Confidence**: HIGH (both call sites read; the try/except boundary at `:845-858` and the argument
  evaluation at `:1365-1383` are unambiguous).
- **Fix sketch**: Hoist `_record_subtitle_transcript` out of the `try` (mirror `_stage_asr_archive`'s
  placement after the archive block) and add a regression test that a cue with a non-numeric time still
  leaves the row `archive: ok` + manifest `archived`.

### [BUG-02] `page_index=0` fabrication can rewrite the wrong part's transcript row on legacy bare-`bvid` rows

- **Evidence**: `bilibili-asr-archive/src/bili_asr/services/queue_source.py:366-372` — the write-backs
  resolve `video_part_id` by `SELECT video_part_id FROM video_parts WHERE bvid = ? AND page_index = ?`;
  the three callers all default a missing page index to 0:
  `coordinator.py:759` and `coordinator.py:798` (`page_index=int(entry.get("page_index") or 0)`),
  `cli/asr.py:294` (same), `cli/pilot.py:605` (same).
- **Impact**: A legacy/unresolved (bare-`bvid`) row archives correctly under its bare-`bvid` stem
  (`archive.py:511-515` `archive_stem` returns the bare `bvid` when `work_id` is absent/`unresolved`, and
  `bundle_paths` keys the same way), but its write-back then resolves `(bvid, 0)` and stamps the transcript
  it just produced onto the **p0** `video_part_id`. The part the archive actually belongs to is not the
  part the store is told about: `v_missing_transcript` keeps the true part and drops the wrong one, and the
  `acquisition_attempts` evidence names p0. Reachable on any manifest whose rows predate the page-identity
  cutover — exactly the case that is a decided by-design *read* compatibility, but the new write path
  converts it into a store fact. (Prior registered root cause I-000133 covers re-queuing of such rows. The
  wrong-row write itself is not registered in the HIGH/MED list I read: not I-000067/105/126.)
- **Effort**: S (guard all four call sites on a page-resolved identity — `work_id` present and
  `page_index` not `None` — and skip the write-back otherwise, with a test).
- **Risk**: MED — skipping shrinks write-back coverage for legacy rows; it must not regress the p-resolved
  rows that the same helper serves (all four sites need the same guard to stay consistent).
- **Confidence**: MED (fabrication and SQL are read directly; the exact population of unresolved rows on a
  live root was not measured — needs one store query to size).
- **Fix sketch**: Resolve the part from the row's `work_id` (`parse_work_id` → page_index) rather than
  `or 0`, and make the helper accept `page_index: int | None` with `None` meaning "skip".

### [BUG-03] Journal replay splits on Unicode line separators, so a legal U+2028/U+2029 row kills all later rows

- **Evidence**: `bilibili-asr-archive/src/bili_asr/manifest.py:253` —
  `for line in raw.decode("utf-8", errors="replace").splitlines():` in `_replay_latest`. The writer is
  `ensure_ascii=False` (`persistence.py:110-116` `_json_line`; `manifest.py:367` `_snapshot_bytes`), so a
  title/text containing U+2028, U+2029 or U+0085 is written raw; `str.splitlines()` breaks on those code
  points as well as `\n`, so one such row yields a first fragment that fails `validate_manifest_record`,
  and the `except ValueError: break` then **stops the replay** — every journaled row appended after that
  byte offset is silently dropped from `_entries`, `load()` and `get()`.
- **Impact**: A single row whose text carries U+2028 (legal JSON, and a character that arrives from
  upstream titles/subtitles) makes the store's own replay produce a truncated ledger: `get()` answers
  "missing" for later keys, `upsert()` of a key "after" the poison row writes a duplicate/competing row,
  and the snapshot/journal compaction then folds the *truncated* view back — the `manifest.jsonl` SSOT
  loses rows that were durably appended. Same root already fixed on the other side of the fence:
  `coordinator.py:311-312` explicitly documents that the attempt tail must be split on `"\n"` only, never
  `str.splitlines()`, for exactly this reason.
- **Effort**: S (split on `"\n"` only — `raw.decode(...).split("\n")` with per-line `.strip()` — plus a test
  with a U+2028-bearing title).
- **Risk**: LOW — behavior is identical for all rows without those separators; the change tightens a parse
  that is already line-oriented.
- **Confidence**: HIGH (both the writer and the reader read; the divergence from the sibling implementation
  is explicit in the source comment).
- **Fix sketch**: Replace the `splitlines()` in `_replay_latest` with a `\n` split (or reuse the same helper
  `coordinator._replay_lines` uses) and add a fixture-based regression test; no on-disk format change.

### [BUG-04] Per-row metadata pacing gate is never wired in production: the small-run skip is unreachable and the seam is test-only

- **Evidence**: `bilibili-asr-archive/src/bili_asr/sources/bilibili_api_gateway.py:763-775`
  (`set_pacing_floor`) and `:789-796` (`_pace`: `if self._pacing_floor is not None and self._pacing_floor <= 1:
  return`); `_pacing_floor` defaults to `None` at `:756-761`, and repo-wide `set_pacing_floor` appears only
  in `tests/test_bilibili_api_gateway.py` (lines 1530, 1542, 1554-1555, 1569) — no production caller, not in
  `cli/meta.py` (gateways constructed at `:90`, `:199`, `:299`).
- **Impact**: The stated motivation for the delta's pacing change — a full-corpus `fetch-meta` page firing
  ~90 back-to-back upstream calls and tripping risk control mid-run — is delivered, but only in the
  unconditional form: every per-row getter pays 0.8-1.6 s even for a single-BVID run. The optimization the
  docstring sells ("a single-bvid / small selection does not [need the delay], so the floor lets that path
  skip the 0.8-1.6 s latency per call") is unreachable in production because no production caller lowers
  the floor, so the only reachable state of `_pacing_floor` is `None` (= always pace). The `set_pacing_floor`
  guard line (`6b37c54`, `:766`) is therefore dead code and the seam is test-only surface. Not a
  correctness defect: the pacing predicate at `:794-795` (`_pacing_floor is not None and _pacing_floor <= 1:
  return`) is internally consistent with the docstring's "does not exceed the floor" reading only if the
  caller passes `1` to mean "this run is small" — the parameter is a *floor to skip at*, not an expected-row
  bound, and that naming/contract mismatch is what a future wiring would get wrong. No second-order risk is
  claimed for the current state.
- **Effort**: XS-S (either delete the seam and its docstring claims, or wire it in `cli/meta.py` and invert
  the predicate to `self._pacing_floor is not None and expected_rows <= self._pacing_floor: return`).
- **Risk**: LOW — the flag is test-only today, so removing/fixing it cannot change production behavior; the
  risk is only picking the wrong direction (delete vs wire) without a product ruling.
- **Confidence**: HIGH for the inertness (grep over src + tests); MED for which direction the fix should
  take (needs the pacing decision registered as I-000053/I-000141 follow-ups), and the "expected-row bound"
  vs "skip-at floor" naming mismatch is read from the docstring, not from a caller.
- **Fix sketch**: Take one ruling — "always pace, delete the gate" or "wire `set_pacing_floor(1 if small
  else 2)` from the enumeration entry point and rename it to say which semantic it carries" — and add the
  missing boundary tests (`N=0` rejected already; `N=1` and `N=2` behavioral).

### [BUG-05] `AttemptLedger` treats a self-inflicted size collision as harmless: the malformed-history re-check is unreachable in the same process

- **Evidence**: `bilibili-asr-archive/src/bili_asr/coordinator.py:236-256` — `append` computes
  `if self._file_size() != self._last_seen_size: self._replay_tail(...)`, then
  `if self._history_malformed: self._revalidate_history()`. `_file_size()` returns `None` on `OSError`
  (`:262-266`), and the fingerprint is compared with `!=` against `None`. The path that matters: an
  in-process append that raises after `append_jsonl_record` wrote a torn line leaves
  `self._last_seen_size` unchanged (it is only updated after the write at `:293`), but the file size *did*
  change, so the next append replays the tail strictly and raises `ValueError("malformed attempt
  history in tail")` — correct fail-closed. The inverse case is not covered: when `_file_size()` answers
  `None` because the sidecar/its directory became unreadable (EACCES, ESTALE on a WebDAV-backed root) and
  `_last_seen_size` is also `None` (fresh instance, or after a prior `FileNotFoundError` reset), the
  comparison is `None != None` → `False`, the replay is skipped, and `_history_malformed` — seeded `True`
  by construction from a *lenient* read of a corrupt history — triggers `_revalidate_history()`, whose
  `OSError` branch raises `ValueError("attempt history unavailable")`. That raise is intended; the gap is
  that the *set* of the fingerprint on the failure paths (`None` on OSError, `:263-264`) makes
  "unreadable" and "unchanged" indistinguishable, so the size-delta detection is silently disabled for the
  rest of the instance's life (every later append on a root whose size reads fail skips the tail replay
  while `_last_seen_size` stays `None` and a *successful* later `_file_size()` returns an int → `int != None`
  → replay, so recovery requires the stat to work again).
- **Impact**: In the non-raising sub-case, the ledger believes it has a complete map seeded from an empty
  history: the seeding path is gated on `os.path.exists(self.path)` (`:216-217`), which is `False` (not an
  error) when the path is merely *unreadable* through a failed stat, so `_history_malformed` stays `False`
  and the map stays empty. A foreign writer that appended before this instance started is then invisible
  until the next size change, and `append` numbers
  attempts `1..N` over the foreign writer's `1..N` — the duplicate-numbering regression I-000149 exists to
  prevent, reachable only through the stat-failure branch. This is a narrow, environment-dependent
  re-entry of the registered defect (cite **I-000149**), not a new class.
- **Effort**: XS (make "unknown fingerprint" a first-class state: on `_file_size() is None` set
  `_last_seen_size = None` **and** force `_revalidate_history()`/strict full replay; or compare
  `(size, )` tuples and treat `None` as "must replay absolute tail from 0").
- **Risk**: LOW (adds a read on an error path only).
- **Confidence**: MED (control flow is read; the stat-failure scenario on the intended WebDAV mount was not
  reproduced — it needs a fault-injection test).
- **Fix sketch**: Represent the fingerprint as `int | None` with an explicit "unknown → replay from 0"
  rule and add a test that fakes `os.path.getsize` raising once.

### [SEC-01] Committed Bilibili cookie jar + a credential-bearing WebDAV URL in a git-tracked JSON inventory

- **Evidence**: `.mstar/plans/…` is not the surface — the finding is in the repo working tree:
  `bilibili-asr-archive/notes/video-inventory/up-videos-coordinate-4.json` lines 23, 30, 51, 58, 79, 93,
  100, 107, 114, 121, 128, 135 (12 hits, pattern type reported as `token`) from the engine's own
  credential scan (`mstar audit secret-scan /root/workspace/bilibili-asr-archive` → `audit.secret-scan.findings`,
  exit 1, 23 hits total). Companion hits in the same scan: `docs/asr-pipeline.html:7855/7927/9239/9651/11867/12217`,
  `.env.example:1` (env-file, expected placeholder), `tests/test_export.py:579/581` (classified
  placeholder by shape), `tests/test_scheduler.py:44` and `tests/test_mixed_outcome_contract.py:35`
  (pattern `secret`, no long token on the line — likely a variable name).
  **No secret value is reproduced here.** File is git-tracked: `git ls-files`-reachable and part of the
  delta-adjacent tree (`ff39fd0..1e756df` does not touch it, so it predates the delta — reported because
  it is live in the working tree and the register has no row for it).
- **Impact**: Attacker model: anyone with read access to this checkout (a fork, a shell history, a backup,
  a future push) obtains (a) a `Cookie`/`SESSDATA`-shaped value that authenticates as the operator to
  Bilibili's API and (b) a WebDAV host URL carrying embedded credentials. Either grants actions as the
  operator's account (Bilibili: playback/session-dependent endpoints; WebDAV: read/write over the archive
  mount the pipeline treats as its storage). Rotating only one leaves the other valid. The values are
  *values*, not symbolic names — the scan reports them as matched credential patterns, so the §6
  "symbolic names are not secrets" exclusion does not apply.
- **Effort**: S (delete the credential-bearing fields from the tracked file or move it out of the repo,
  then rotate both credentials — Bilibili SESSDATA re-login and the WebDAV account password — and re-run
  `mstar audit secret-scan` to a clean exit).
- **Risk**: LOW for the file edit; the rotation is the disruptive half (the pipeline's SESSDATA and the
  WebDAV mount must be re-provisioned everywhere they are used).
- **Confidence**: MED — the engine pattern table matched and the file/line anchors are verified; the
  *liveness* of each value was not tested (and must not be, per §12 read-only rules). Treat as live until
  proven placeholder by the owner.
- **Fix sketch**: Strip the fields, rotate both credentials, add the inventory path to the never-commit
  set, and re-scan. If the file is intended as shared inventory, keep only non-credential fields.

### [SEC-02] Caption write-back infers `source_kind` from a language prefix, so a non-AI machine track can be stored as `subtitle-ai`

- **Evidence**: `bilibili-asr-archive/src/bili_asr/coordinator.py:1326-1352` —
  `_caption_source_kind_from_entry` returns `"subtitle-ai" if language.startswith("ai-") else "subtitle-cc"`,
  and `_caption_language_from_entry` (`:1355-1374`) reads `sub_lan` / `subtitle_language` off the manifest
  row. `storage/database.py:1139+` `record_local_transcript` validates against the singleton
  `ALLOWED_LOCAL_TRANSCRIPT_SOURCE_KINDS`, while the caption path
  (`record_acquired_transcript`) is the one that enforces `ALLOWED_CAPTION_SOURCE_KINDS` — and it is called
  from `queue_source.record_caption_transcript` (`services/queue_source.py:420-460`) with whatever kind the
  caller passed. The stored value is data that later surfaces in `search --source`, `export` and the
  `v_missing_subtitle`/transcript identity, i.e. an attacker-influenced-but-server-side field on the
  report surface, not a security boundary crossing.
- **Impact**: A row whose `sub_lan` is `ai-…` for any reason other than a machine caption (an upstream
  language tag like a filtered variant, or a hand-edited manifest row — manifests are operator-writable
  data the tool reads as authoritative) is durably recorded as `subtitle-ai`: the archive's provenance
  claim "this text is a machine caption" becomes wrong and is not re-derivable (the raw caption document is
  the only other copy). Consequence class: misattributed provenance in the published bundle + the store's
  `source_kind` filter, not privilege escalation. On this single-user CLI the blast radius is the archive's
  own integrity, so this is **severity low** by the §2 anchors — reported because the sibling typed
  subtitle-arm resolves the kind from the track's `is_ai` flag, so two routes now disagree about how the
  kind is derived.
- **Effort**: XS (have the caption write-back take the kind from the same `is_ai`-derived track metadata the
  typed arm uses; keep the prefix as a fallback only when the row also names the track).
- **Risk**: LOW (the store's validator already rejects unknown kinds; only the derivation changes).
- **Confidence**: MED (the two derivations are read; which one the subtitle harvest seam actually records
  into `sub_lan` for a machine track was not traced to the gateway response field in this budget).
- **Fix sketch**: Route both arms through one `caption_source_kind(track)` helper and add a test for a
  non-AI track whose language string happens to start with `ai-`.

---

## Registered — not re-reported

- **I-000149** (attempt-ledger map): still open; the delta's fix is substantially present
  (`coordinator.py:236-300`, tail replay with `\n`-only splitting, bounded fingerprint window). BUG-05 is
  the one residual re-entry I could evidence, cited to this row rather than as a new finding.
- **I-000067 / I-000105 / I-000126** (ASR store write-back): the delta *implements* the write-back
  (`storage/database.py:1139`, `services/queue_source.py:329/390`, wired at `coordinator.py:990`,
  `cli/asr.py:290`, `cli/pilot.py:600`). I did not verify it end-to-end on a live store — see truncated
  coverage. This is the delta's answer to those rows; no new finding.
- **I-000141** (pacing blocks the event loop): *fixed in the delta* — `_sleeper` now defaults to
  `asyncio.sleep` (`bilibili_api_gateway.py:741-746`) and `_pace` awaits it (`:789-796`). The remaining gap
  is BUG-04 (gate never wired), not the blocking call.
- **I-000139** (`is_stale` journal-blind): *fixed in the delta* — `search_index.py:510-525` now takes
  `max(mtime(manifest), mtime(journal))` and imports `JOURNAL_NAME` from `manifest`.
- **I-000127** (per-hit snippet N+1): *fixed in the delta* — batched
  `_snippets_for_hits`/`_titles_for_bvids` with `_IN_CHUNK = 900` (`search_index.py:1585-1640`), keeping
  `_probe_videos_readable` on the empty path so the defect class (exit 1) is preserved.
- **I-000156 / I-000068 / I-000066 / I-000161** (store route cannot express harvest-eligible rows): the
  delta's `entry_for_item` gap→status map (`queue_source.py:85-89`) and the `meta_ok` override
  (`:204-208`) are the change; I-000161 asserts the mapping is behaviorally inert, which matches what I see
  (statuses `needs_audio`/`meta_ok` land in different skip sets only if the caller honors them).
- **I-000042**: `meta_ok` remains a non-`ALLOWED_PROCESSING_STATUS` value (models.py:25
  `{"discovered","metadata_collected","gone"}`); the new map makes it a *manifest* status derivable from a
  queue-backed item, so the existing row's scope grows rather than shrinking.

## Hardening / checked-and-clean (no plan needed)

- SQL assembly in the delta's new code: `search_index.py` interpolates only `STORE_FTS5_TABLE`,
  literal column lists and generated `?` placeholders (checked `:64`, `:159-162`, `:190-196`, `:1325`);
  `database.py`'s new `record_local_transcript` and `queue_source`'s three new resolvers bind every value
  (`:366-372`, `:429-434`). No data-derived identifier or fragment. **Checked and clean.**
- Path confinement: the delta's new write-backs resolve rows through the store and write no files;
  `integrity.py`'s new D5 branches (`:426-437`, `:640-650`, `:665-672`) only *narrow* inferred candidates
  (identity-invalid rows contribute none), and declared paths are still probed through `_safe_over_bases`.
  **Checked and clean.** One asymmetry worth a follow-up line: `quality._canonical_stem`
  (`quality.py:365-376`) swallows `KeyError/TypeError/ValueError`, while
  `integrity._canonical_required_paths` (`:665-672`) and `_required_paths` (`:640-650`) catch the same
  tuple — consistent, but `_artifact_paths` (`quality.py:415-431`) treats a `None` stem as
  `artifact_missing` *only* because the `identity_invalid` gate at `quality.py:266-278` fires first; a row
  with a non-`int` `cid` and declared paths is the only path that reaches the inferred branch with a `None`
  stem.
- Credential redaction on display paths: no new leak site in the delta's print paths (`cli/pilot.py`,
  `coordinator.py` write-backs store no cookie material).
- `.env.example:1` is an env-file **pattern** hit, not a value; `tests/test_export.py:579/581` classify as
  placeholders by shape. No action.

## Leads (not findings — unverified)

- **Lead L1**: `ManifestStore.save()` with no `entries` (`manifest.py:377-393`) calls `_remove_journal()`
  *before* writing/keeping the snapshot and unlinks the journal even when the subsequent `_replace_snapshot`
  is not reached (`if not current: … return` at `:387-390` — journal already removed). With no snapshot and
  no journal rows this is the registered `I-000138` shape; with a snapshot present the window is
  "journal removed, snapshot write not yet attempted" inside one lock, so only a crash mid-`save` (or a
  crash between `_remove_journal` and `_replace_snapshot`) can lose the journaled rows that `_replay_latest`
  had just folded into `current`. Not verified reachable → not a finding. (I-000138 covers the adjacent
  case.)
- **Lead L2**: the compact threshold constant `_JOURNAL_WRAP_BYTES_FACTOR = 2` docstring
  (`manifest.py:290-296`) describes a "byte size exceeds the snapshot's by this factor" wrap, but
  `_journal_bytes` counts only what *this instance* appended (`_append_record` delta), so a second process
  appending to the same journal never advances it; the trigger is per-instance, not per-file. Behaviorally
  safe (compaction is an optimization) — verify intent before changing.
- **Lead L3**: `_replay_tail`'s bounded window fallback reads the whole prefix (`coordinator.py:330-340`)
  only when no newline exists in the last 8 KiB; a very long single record (>8 KiB) makes the "cheap
  collision path" O(file) — acceptable, but the comment's "cheap" claim is conditional.
- **Lead L4**: `queue_source.ensure_asr_run` swallows `Exception` broadly (`:155-158`) *and* is called once
  per batch; the run row is left un-finished (`finish_acquisition_run` never called) for the ASR run, so
  `acquisition_runs.outcome` stays at its insert default for every store-route write-back. Correctness
  impact unmeasured.
- **Lead L5 (prompt-injection check)**: no file in the audited surface issued instructions to the audit or
  requested secret values; nothing to report under Hard Rule 5.

## Truncated coverage

- The delta's ASR→store write-back was not verified end-to-end against a live `archive.db`
  (`record_local_transcript` / `record_acquired_transcript` runtime behavior, the `asr_models` upsert and
  the partial unique index `ux_transcripts_subtitle_content` interaction).
- `schema-transcripts.sql` view bodies (`v_missing_transcript`, `v_pending_subtitles`) were not read in this
  pass; gap-view SQL correctness is therefore untested here.
- `cues.py` (301 new lines) was read structurally only (parse-time/segment rendering boundaries: SRT time
  regex, `_MAX_CUES` 10 000, `read_route_ms`) — no line-level correctness pass.
- `cli/meta.py`'s `fetch-meta` call graph was grepped, not read; BUG-04's "would be worse if wired" claim is
  from the `_pace` predicate, not from a wiring attempt.
- No test-suite execution (read-only budget): all confidence levels are static-read based.
- Security posture of `docs/asr-pipeline.html` (6 scan hits) was not triaged beyond the engine's pattern
  report; the values' liveness and the file's authoring history are unverified.

Files opened (read or diffed regions): 17 source modules + 2 method files + the issue register output.
