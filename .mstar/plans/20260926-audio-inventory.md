---
plan_id: 20260926-audio-inventory
iteration: iter-2026-09-metadata-audio-layout
iteration_compass: .mstar/iterations/iter-2026-09-metadata-audio-layout/delivery-compass.md
primary_spec: .mstar/iterations/iter-2026-09-metadata-audio-layout/specs/audio-retention-contract.md
iteration_refs:
  - .mstar/iterations/iter-2026-09-metadata-audio-layout/specs/audio-retention-contract.md
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

# Make the downloaded audio inventoried and un-silenceably retained

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. Steps use
> checkbox (`- [ ]`) syntax for tracking.
>
> **This plan is NOT yet dispatched.** It is registered as a plan of iteration
> `iter-2026-09-metadata-audio-layout`, which is registered and **`locked`** as of 2026-09-26 — the Phase-1
> review-and-edit chain completed (all three seats ran, every marker cleared). Two independent gates hold dispatch: the compass must reach
> `locked`, and the compass `## Blocked By` serial-dispatch rule must lift. Registration authorises no
> implementation.
>
> **Second in the capacity order (compass D13):** if the window fits only one of the iteration's two plans,
> `20260926-video-metadata-enrichment` takes the slot and **this plan gives way** — it is the smaller change
> but the later complaint, and deferring it costs queryability only (see the Goal below).
>
> **What the title does and does not claim.** "Un-silenceably retained" describes a property the shipped code
> **already has** — `KEEP_AUDIO_DEFAULT = True` (`artifact_root.py:87`), nothing hard-codes a reclaim, and the
> behaviour is already pinned by tests. This plan does **not** add retention, does **not** add a persistence
> default, and does **not** write the first retention tests; it adds the **inventory** and closes two narrow
> coverage holes in an already-tested surface. Per compass **D6**, no document in this package — this header
> included — may claim otherwise.

**Goal:** Make it possible to answer "which audio do I have, and where is it" from the store, and pin the two
retention/reclaim behaviours that are real today but have no test holding them in place.

**Why the retention half is small and cannot grow:** the operator's complaint is *"流水线过程中下载的音频文件
应当持久化的保存"* — and the investigation's first finding is that this is **already** the code's behaviour
(`KEEP_AUDIO_DEFAULT = True`; `tests/test_audio_retention_policy.py` already pins four cases;
`tests/test_audio_reclaim.py` already pins eleven). The gap this plan closes is **visibility**, not
retention: the store cannot answer which audio exists, because `audio_objects` / `part_audio_objects` have
never had a writer. What the retention half adds is two characterisation tests for behaviour that is believed
correct — a pin, not a repair. If either of those tests goes **red**, that is a **data-loss defect** and the
task stops for a PM decision (Task 3 Step 2) rather than being repaired in place.

**Architecture:** Two halves that share a premise.

1. **Inventory.** `audio_objects` and `part_audio_objects` have existed in `storage/schema.sql:92-110` since
   the metadata plan, documented as "intentionally empty", and **nothing in `src/` reads or writes them**
   (verified by grep; the only `INSERT`s into them live in `tests/test_storage_schema.py:710-775`). This plan
   gives them their first writer and reader, so the audio a download produced is a queryable fact rather
   than an inference from a JSONL line and a directory listing. **This is the whole of the feature.**
2. **Two narrow coverage gaps** in the retention and reclaim surfaces, found by *checking* rather than
   assuming. Retention is already the default (`KEEP_AUDIO_DEFAULT = True`, `artifact_root.py:87`) **and
   already tested** (`tests/test_audio_retention_policy.py`, 4 cases); reclaim is already tested
   (`tests/test_audio_reclaim.py`, 11 cases). What remains unpinned: the **flag's precedence** over
   `BILI_KEEP_AUDIO`, and the **sibling-page** scenario for a reclaimed row's derived candidate.

**Tech Stack:** Python 3.12, SQLite 3, `hashlib` (sha256 over the audio file), pytest.

**Execution:** mstar-sdd

**Main worktree branch**: `main` (recorded 2026-09-26; the control root stays on `main` — never switched).

## Global Constraints

- **Naming discipline.** Every new identifier passes `naming-analyzer` before it lands, with rejected
  alternatives recorded. The names below are already through that pass; use them verbatim.
- **The two tables already exist and are pinned.** `audio_objects` and `part_audio_objects` are in
  `BASE_TABLES` and `EXPECTED_TABLE_COLUMNS` (`tests/test_storage_schema.py:52-57` and its map) and
  `test_schema_inspection_matches_the_declared_contract` (`:856-865`) asserts their exact columns and
  foreign keys. **Do not add, rename or drop a column** on either table — that would force an
  `archive.db` rebuild on every operator (the `CREATE ... IF NOT EXISTS` rule below) for no reader benefit.
- **Schema evolution policy.** `initialize_schema` (`storage/database.py:154-172`) runs only
  `CREATE ... IF NOT EXISTS`, and `SchemaContractError` (`:68-73`) states the policy: "The archive database
  is rebuildable by policy, so there is no migration path". Both tables already exist everywhere, so this
  plan needs **no schema change at all** — that is the point of using them.
- **`store.db` is absent on this host** (`store.not-initialized`). Residual accounting for this plan goes to
  the project register file and the plan's own residual section, never to a claim that a store-backed issue
  was filed. Do not run `mstar store init` to make a step look tidier.
- **No new upstream call, no network.** This plan touches only local files and the local store.
- **Do not widen the audio confinement.** Every path used here goes through
  `path_policy.confined_audio_path` / `confined_audio_file` / `unlink_confined_audio`. A raw
  `open(path)`/`os.stat(path)` on a stored audio string is a defect; the guard
  (`path_policy.py:25`, `declared.parts[0] != "audio" or len(declared.parts) != 2`) is the contract.
- **`asr.py` is out of scope for this plan.** Another live session is actively editing it (it committed
  `0a95035` and `83ba8d0` on 2026-09-26 while this plan was written — both touching `_read_audio` and the
  test seam). The `/tmp` materialize behaviour is described in `## Current state` as context, and is
  deliberately **not** a task here.
- **Verification scope.** `mstar-harness-core` § 定向执行与验证边界 — only changed behaviour and its direct
  contracts; the full suite is CI's. Each task gates on its own named pytest selector.

## Naming decisions

| Thing | Chosen | Rejected | Why |
|---|---|---|---|
| Plan id | `20260926-audio-inventory` | `audio-persistence` | Retention is already the default, so "persistence" would name the operator's fear rather than the actual gap (no DB visibility + no guard). The id must be true of the change. |
| New command | `derive-audio-inventory` | `sync-audio`, `scan-audio` | Mirrors the shipped `derive-manifest`, which is the same shape of operation (store-read → reconciliation) and is already in the operator's vocabulary. `sync` implies two-way convergence; `scan` implies a pure read. |
| Service module | `services/audio_inventory.py` | extend `sidecar_projection.py` | The sidecar module is a read-only JSONL projection layer; this is a store writer. Different direction, different home. |
| Repository method | `record_audio_object` / `link_part_audio` | `insert_audio`, `add_audio` | Matches the repository's existing `record_*` family (`record_acquired_transcript`, `record_subtitle_attempt`). |
| Retention test name | `test_audio_retention_default_survives_a_command_without_the_flag` | `test_keep_audio_default` | The name must state the property being protected, not the symbol being read. |

## Current state (verified 2026-09-26 at `9d530cd`)

### What already holds the audio

| Aspect | Today | Anchor |
|---|---|---|
| Write target | `{artifact-root}/audio/{bvid}.p{page}.m4a`, or `.flac` when ffmpeg is unavailable | `audio.py:229-260`, staged as `.audio-stage-<hex>.download` (`:90`, `:108-121`) |
| Retention default | **retain** — `KEEP_AUDIO_DEFAULT = True` | `artifact_root.py:87` |
| Policy resolution | flag → `BILI_KEEP_AUDIO` (`"1"`/`"0"`) → default | `resolve_keep_audio`, `artifact_root.py:186-197` |
| Reclaim | only when the resolved policy asks; deletes under **both** bases | `audio_reclaim.reclaim_audio`, `:64-105`; `Coordinator._reclaim_audio`, `coordinator.py:542-556`; `_reclaim_after_archive`, `cli.py:2341-2360` |
| Flag pair carried by | `asr`, `pilot`, `run`, `schedule`, `campaign` | `cli.py:157`, `:181`, `:351`, `:399`, `:445` (`_KEEP_AUDIO_HELP`) |

So the operator's fear ("audio gets deleted") is **not** what the code does by default. What the code
actually lacks is the two things below.

### Gap 1 — the audio inventory is not queryable

- `audio_objects(audio_id, sha256, byte_size, format, duration_ms, storage_key, created_at)` and
  `part_audio_objects(video_part_id, audio_id, acquired_at, acquisition_source)` exist in
  `schema.sql:92-110`.
- **No writer, no reader.** `grep -rn 'audio_objects\|part_audio_objects' src/` returns only the two
  `CREATE TABLE` statements. The live store confirms 0 rows in both while `transcripts` holds 6 and
  `transcript_segments` 8254.
- Consequence: the only way to learn which audio exists is to read `manifest/manifest.jsonl`
  (`audio_path` keys) and `ls` the `audio/` directory, then guess whether they agree. The store — the
  surface `status`/`runs`/`publish-transcripts` already read — cannot answer it.

### Gap 2 — two narrow coverage holes in an otherwise well-tested surface

**Corrected 2026-09-26.** An earlier draft of this plan asserted "retention is an untested default". That
assertion was **false**; it was withdrawn after opening the test files. The shipped coverage is real:

| Suite | Lines | What it already pins |
|---|---|---|
| `tests/test_audio_retention_policy.py` | 113 | `BILI_KEEP_AUDIO=1` retains · **unset defaults to retain** · `=0` deletes · `RunCoordinator` honours the value after a row is archived |
| `tests/test_audio_reclaim.py` | 189, 11 cases | m4a delete · subtitle-only no-op · bare-bvid fallback with no file · path traversal · absolute-path escape · in-`audio/` reclaim · `.flac` candidate · symlink escape · name-swap race · coordinator archive-stage reclaim |

What genuinely remains unpinned — and is the whole of this plan's retention half:

1. **Flag precedence.** All four existing retention cases call `resolve_keep_audio(None, ...)`; none passes a
   non-`None` flag. The shipped rule is *flag wins outright* (`artifact_root.py:190-191`) and is what an
   operator relies on when overriding a globally exported `BILI_KEEP_AUDIO=0`.
2. **The sibling-page scenario.** Every existing reclaim case uses a single row. No test places a sibling
   page's file in the same `audio/` directory while one row is reclaimed, so the derived candidate's blast
   radius is unpinned.

Context that is a structural property rather than a hole: the five commands carrying `--keep-audio` are
exactly the five that can archive; the other fifteen (`fetch-meta`, `status`, `runs`, `probe-subs`,
`harvest-subs`, `download-audio`, `derive-manifest`, `publish-transcripts`, `search`, `coverage`, `verify`,
`recover`, `evaluate-concurrency`, `export`, `check-asr-env`) never reclaim because they never call
`_reclaim_after_archive` — verified by the absence of the call, not by the absence of the flag.

### Context that is explicitly NOT in scope

`ASRRunner.transcribe` always receives a `/proc/self/fd/N` path (the chain wraps every call in
`confined_audio_file`, `cli.py:2261`, `:2467`; `coordinator.py:579`), so `_materialize_input`
(`asr.py:304-318`) copies the **entire** audio file into `$TMPDIR` on every row and unlinks it in the
`finally` (`:793-798`) — a second full copy per row, invisible to the DB. That is real, it is measured, and
it belongs to a different plan: it touches `asr.py`, which the live session is editing right now. Recorded
here so the next reader does not re-derive it, and as the recommended subject of a follow-up plan.

## Task 1: Record the audio object and its part link  — **SUPERSEDED 2026-09-28: do not execute**

**Effort (agent-oriented):** M

**Split point:** If `download_audio` turns out to be callable with no `ManifestStore` in a path the tests
exercise (`store=None` is a supported argument, `audio.py:186`), stop after the repository half (Steps 3-4 on
`record_audio_object`/`link_part_audio` plus their tests) and report — wiring the command then needs its own
task, because the entry point differs.

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/storage/database.py` — add `record_audio_object` and
  `link_part_audio` to the repository that already owns `video_parts`
- Modify: `bilibili-asr-archive/src/bili_asr/storage/models.py` — add `AudioObjectRecord` (the tables'
  existing columns only)
- Modify: `bilibili-asr-archive/src/bili_asr/services/audio_inventory.py` — **create**; the pure function that
  turns an observed audio file plus its manifest row into the two records
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py` — call it from `_cmd_download_audio` (`:1521`) after the
  manifest reaches `audio_ok`
- Test: `bilibili-asr-archive/tests/test_storage_schema.py` (the tables' existing pin must keep passing),
  a new `bilibili-asr-archive/tests/test_audio_inventory.py`
- Out of scope: `asr.py` and the `/tmp` copy; widening `_candidate_paths` (Task 3 tests its current shape);
  `publish-transcripts`; backfilling rows for audio already on disk (Task 2).

**Interfaces:**
- Consumes: `audio_objects` / `part_audio_objects` as declared (`schema.sql:92-110`);
  `MetadataRepository.transaction` (`database.py:287`); `path_policy.confined_audio_path`; the
  `{audio_path, bvid, page_index, cid, work_id}` shape the manifest row already carries.
- Produces: `AudioObjectRecord(audio_id: int | None, sha256: str, byte_size: int, format: str,
  duration_ms: int, storage_key: str, created_at: int)`;
  `MetadataRepository.record_audio_object(record) -> int` (returns `audio_id`; idempotent **by `sha256`**,
  and refreshing in place when the same `storage_key` is observed with a new digest — `storage_key` holds the
  **root-relative declared string** per compass **D14**, never an absolute path);
  `MetadataRepository.link_part_audio(video_part_id: int, audio_id: int, acquired_at: int,
  acquisition_source: str) -> None` (idempotent on the composite primary key).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_audio_inventory.py
def test_a_downloaded_row_becomes_a_queryable_audio_object(tmp_root):
    """The store can answer "which audio do I have" after one download.

    The premise this pins: today ``audio_objects`` is empty no matter how many
    downloads ran, so this query is the whole feature.
    """
    # arrange: one manifest row in ``needs_audio`` with a real (tiny) .m4a on disk
    # act: run the download path's store write
    # assert:
    #   row = connection.execute("SELECT * FROM audio_objects").fetchall()
    #   assert len(row) == 1
    #   assert row[0]["format"] == "m4a"
    #   assert row[0]["byte_size"] == os.path.getsize(audio_file)
    #   assert row[0]["sha256"] == hashlib.sha256(audio_bytes).hexdigest()
    #   assert connection.execute("SELECT COUNT(*) FROM part_audio_objects").fetchone()[0] == 1


def test_recording_the_same_audio_twice_does_not_duplicate_it(tmp_root):
    """``sha256`` is the identity: a re-download of identical bytes is one object."""


def test_a_changed_file_under_the_same_declared_key_refreshes_in_place(tmp_root):
    """The identity rule and the uniqueness rule must agree, not collide.

    ``audio_objects`` is ``UNIQUE`` on **both** ``sha256`` and ``storage_key``
    (``schema.sql:94``, ``:98``).  A writer that conflicts only on ``sha256``
    raises ``IntegrityError: UNIQUE constraint failed:
    audio_objects.storage_key`` when the *same name* holds *new bytes* — and
    this task's own non-fatal rule would swallow it, leaving a stale digest for
    a file that changed.  So: the same ``storage_key`` observed with a new
    digest updates that row in place (same ``audio_id``, new ``sha256`` and
    ``byte_size``), and the ``part_audio_objects`` link is not disturbed.
    """
```

- [ ] **Step 2: Run the test — expect FAIL**

Run: `python -m pytest tests/test_audio_inventory.py -v`

Expected: the first assertion fails — `len(row) == 0`, because nothing writes the table today.

- [ ] **Step 3: Minimal implementation**

`services/audio_inventory.py` holds one pure function and no I/O beyond a read of the already-confined file
descriptor:

```python
def observe_audio(
    *, audio_path: Path, declared: str, work_id: str, video_part_id: int,
    moment: int, source: str,
) -> tuple[AudioObjectRecord, PartAudioLink]:
    """Turn one on-disk audio file into the two records the store holds.

    ``declared`` is the root-relative string the manifest records
    (``audio/<stem>.m4a``) and is exactly what ``storage_key`` stores: the same
    value the manifest uses, so the two surfaces cannot disagree about which
    file a row names.  ``format`` is the suffix without its dot.
    """
```

`storage_key` stores **the manifest's declared relative string**, not an absolute path: it is the value the
reader already resolves over the ordered base pair (`artifact_root.resolve_audio_path`, `artifact_root.py:272`),
so no new resolution rule is invented. `sha256` is computed by streaming the confined descriptor.

**Ruled by the architect review (2026-09-26): root-relative is binding, and the alternative is refused.**
This is compass **D14**; the argument is the artifact-root contract's:

- **D7** (register `:45`, argued §5) keeps every recorded artifact path — `audio_path`, `srt_path`,
  `txt_path`, `md_path`, `raw_path` — **artifact-root-relative** "with its shipped shape", and **D12**
  records the root "**nowhere durable** (no sidecar, no manifest field)". An absolute `storage_key` would
  write a root into the store durably — the second source of truth D12 forbids — and go stale the moment the
  operator moves `audio/`, which `## Non-Goals` in the compass says is the operator's own move to make.
- **D8** resolves a recorded path over the ordered base pair, each candidate validated at its own base. An
  absolute key would need a **new** resolution rule or a baked-in base — the cross-root computation D8
  rejects. The relative key needs neither: it is exactly the value `resolve_audio_path` already takes.
- **The guard refuses an absolute key outright.** `path_policy._audio_parts` (`:16-29`) returns `None` for an
  absolute path (as it does for `..`, a first component other than `audio`, or a length other than 2), so an
  absolute `storage_key` could not be handed to `confined_audio_path`, `unlink_confined_audio` or
  `resolve_audio_path` at all.
- **Identity would be corrupted.** `storage_key` is `NOT NULL UNIQUE` (`schema.sql:98`, pinned at
  `tests/test_storage_schema.py:201`) while `sha256` is the intended identity, so absolute keys would split
  one logical object into two rows the day it is observed under a second root.

**A writer defect falls out of the same review and is part of this task, not a follow-up.**
`record_audio_object` as first specified (`INSERT ... ON CONFLICT(sha256) DO NOTHING`, then
`SELECT audio_id ... WHERE sha256 = ?`) cannot satisfy **both** unique constraints. **Measured:** re-observing
the same declared key with changed bytes raises
`IntegrityError: UNIQUE constraint failed: audio_objects.storage_key` — and this task's own "non-fatal to the
download" rule would then **swallow** it, silently leaving a stale `sha256`/`byte_size` for a file whose
bytes changed. That is precisely the stale-digest case Task 2's `--deep` exists to detect, so the two tasks
cannot be allowed to disagree about it. **Measured remedy:** when the declared key already names a row,
refresh it **in place** — `UPDATE audio_objects SET sha256 = ?, byte_size = ?, format = ?, duration_ms = ?,
created_at = ? WHERE storage_key = ?` — and never delete-and-reinsert: the `part_audio_objects` foreign key is
`ON DELETE RESTRICT` and **blocks** the delete (measured: `IntegrityError: FOREIGN KEY constraint failed`).
So `record_audio_object` has two branches, in this order: (1) the `sha256` already has a row → return its
`audio_id` (the same file seen twice; converges, and the plan's idempotency claim holds); (2) the declared
key already names a row but the digest is new → update that row in place and return its `audio_id` (the same
*name* holding new bytes); (3) neither → insert. One row per declared key, its digest always the last
observation's — which is what makes `storage_key` and `sha256` identities of the same thing rather than two
rules that can disagree.

In `database.py`, `record_audio_object` resolves as above — **`sha256` first, then the declared `storage_key`,
then insert** — never a bare `ON CONFLICT(sha256) DO NOTHING`, and never a delete-and-reinsert (the
`part_audio_objects` FK is `RESTRICT`). `link_part_audio` uses `ON CONFLICT(video_part_id, audio_id) DO
NOTHING`. Both take their connection from the caller's `transaction()` — never open their own.

In `cli.py`, call the pair from `_cmd_download_audio` after the row reaches `audio_ok`, inside the existing
repository transaction, and make the call **non-fatal to the download**: a failed inventory write must not
lose a downloaded file. Report it on stderr in the command's existing style and keep the exit code as the
download's own.

- [ ] **Step 4: Run the affected tests — expect PASS**

Run: `python -m pytest tests/test_audio_inventory.py tests/test_storage_schema.py -v`

`test_schema_inspection_matches_the_declared_contract` must still pass **unchanged for `audio_objects` and
`part_audio_objects`** — this task adds no column and no table of its own.

**Cross-plan note (architect review 2026-09-26): the test's *maps* may legitimately move under this
task's feet, and that is not a failure of this plan.** `20260926-video-metadata-enrichment` adds
`video_tags` and `video_details` and therefore adds entries to `BASE_TABLES` (`:47`),
`EXPECTED_TABLE_COLUMNS` (`:69`), `EXPECTED_FOREIGN_KEYS` (`:173`) and `EXPECTED_PRIMARY_KEY_INDEXES`
(`:205`) — **the same file, `tests/test_storage_schema.py`, that this plan's Step 4 runs**. The two plans do
not collide on a schema object (D3 vs D7: four new child tables on one side, zero schema change on the
other), but they do share this test file. So the invariant this task must hold is **narrower and exact**:
`audio_objects` and `part_audio_objects` keep their declared columns, foreign keys and primary keys, and
their `EXPECTED_UNIQUE_CONSTRAINTS` entries (`:201`) stay as written. A map entry for a *sibling* table
appearing in the same commit is expected, not drift — do **not** "restore" the file, and do not read a
non-empty diff there as evidence that this plan changed the audio schema. If D13's capacity order means this
plan runs **after** the metadata plan, the entries are already present; if it runs first, this task leaves
them absent and adds none.

- [ ] **Step 5: Commit**

## Task 2: `derive-audio-inventory` — reconcile the store with what is on disk

**Effort (agent-oriented):** M

**Split point:** If scanning the real corpus root (6 files / ≈1.1 GB on this host, or a larger archive)
takes more than a few seconds per hundred files, stop after the manifest-only half and report — the
`--deep` hashing mode then becomes its own task with its own cost decision.

**Files:**
- Create: `bilibili-asr-archive/src/bili_asr/services/audio_inventory.py` (extend Task 1's module with the
  reconciliation function)
- Modify: `bilibili-asr-archive/src/bili_asr/cli.py` — register `derive-audio-inventory` beside
  `derive-manifest` (`:273`) and implement its handler beside `_cmd_derive_manifest` (`:1205`)
- Test: `bilibili-asr-archive/tests/test_audio_inventory.py`
- Out of scope: deleting anything (this command is additive and read-only over the audio tree);
  `README.md` prose (Phase 1 routes documentation to `writing-specialist`).

**Interfaces:**
- Consumes: `ManifestStore.load()`, `MetadataRepository.record_audio_object` / `link_part_audio` (Task 1),
  `artifact_root.ArtifactRoots.read_bases()`.
- Produces: a CLI command with the exit taxonomy **0** ran (including a zero-row reconciliation — an empty
  result is success, matching `derive-manifest`), **1** a shipped refusal path (missing/unreadable
  `archive.db`, held writer lock, usage error), **2 unused**. One summary line:
  `derive-audio-inventory: recorded=<n> already=<n> missing=<n> unlinked=<n>`, whose four counters are
  defined by `specs/audio-retention-contract.md` §3.1 (product definitions — implement them as written, and
  if a counter cannot be computed as defined, STOP and report rather than redefining it locally).

- [x] **Step 1: Write the failing test**

```python
def test_derivation_records_present_audio_and_reports_absent_audio(tmp_root):
    """The four counters are distinct, and their meanings are the spec's (§3.1).

    ``recorded`` / ``already`` / ``missing`` / ``unlinked`` are defined in
    ``specs/audio-retention-contract.md`` §3.1; this test is their executable
    form.  ``missing`` is *named-but-absent* (the shipped reclaim path and a
    manual delete both produce it): the command must say the row names a file
    that is not there, not invent one and not delete the row.  ``unlinked`` is
    the object no ``part_audio_objects`` row attributes to a part.
    """
```

- [x] **Step 2: Run the test — expect FAIL** (`no such command`)

Run: `python -m pytest tests/test_audio_inventory.py -k derivation -v`

- [x] **Step 3: Minimal implementation**

Reuse the existing command shells: the same `_open_subtitle_connection(..., read_only=False)`-style guard
family the sibling queue bridge uses for its store access, the same one-summary-line contract, and
`ManifestStore` for the manifest read. The candidate set is the manifest's own rows that carry an
`audio_path`, read through the store's existing API — do **not** write a new `ls`-driven scan as the source
of truth; the filesystem is consulted only to answer "is it there".

`--deep` (optional, default off) additionally computes and stores the `sha256` for objects whose row is
absent from `audio_objects`. **The non-`--deep` behaviour is decided here, once, so the implementer does not
choose between two reachable behaviours:** without `--deep` the command computes the digest anyway, from a
**single-pass streamed read** of the file, and records it. `sha256` is `NOT NULL UNIQUE` on
`audio_objects` (`schema.sql:94`) and is the identity every later reconciliation matches on, so a row
without one is a row the store cannot deduplicate — and the streamed pass is the same read the size probe
already pays for. `--deep` is therefore **not** a "hash or don't" switch; it re-verifies the digest for an
object whose row is **already present** (`record_audio_object` is idempotent on `sha256`, so a changed file
would otherwise keep the old row's identity without complaint).

Pin both readings in the test: a run **without** `--deep` records a row **with** a correct digest, and a
second run over the same file increments `already` rather than inserting a second row.

**`missing` and `unlinked` are distinct, and their definitions live in the spec, not in the implementer's
reading of a counter name.** `specs/audio-retention-contract.md` §3.1 defines all four counters; `missing` is
*named-but-absent* (the manifest names `storage_key` and no file is there — the shipped reclaim path and a
manual delete both produce it) and `unlinked` is an observed object that **no `part_audio_objects` row
attributes to a part**. Both are newly written product definitions: the shipped code names neither. Implement
them as written; if one cannot be computed as defined, STOP and report rather than redefining it locally.
Neither counter authorises a write — the command is additive and read-only over the audio tree, and a row in
either counter is reported, never invented and never deleted.

This makes the command's cost model explicit rather than incidental: one streamed read per **newly
recorded** file; zero file reads for a candidate whose `storage_key` already has a row and is not passed to
`--deep`; zero reads for a row that resolves nowhere. If a corpus-scale run makes that too slow (the
measured corpus is 6 files / ≈1.1 GB), the cost decision belongs to the split point above — stop after the
manifest-only half and report — not to a silent "skip the hash" branch shipped in the code, which would
break the `NOT NULL` column outright.

- [x] **Step 4: Run the affected tests — expect PASS**

Run: `python -m pytest tests/test_audio_inventory.py -v`

- [x] **Step 5: Commit**

## Task 3: Two narrow coverage gaps in the retention and reclaim surfaces  — **DEFERRED 2026-09-28: not executed; waived, do not read as delivered**

> Deferral record. This task is **XS** and its subject already passes: AC 5 is met by
> `tests/test_audio_retention_policy.py` + `tests/test_audio_reclaim.py` (**13 passed, 2 skipped**), and this
> task only adds two further characterisation cases over behaviour that already works. The iteration closed on
> its acceptance criteria (AC 4/5/6), and Task 3 was waived rather than run — tracked as residual **A-R9** so it
> is a recorded decision, not an omission. Its five Steps are deliberately left unchecked because they were
> genuinely not performed.

**Effort (agent-oriented):** XS

**Correction recorded during plan authoring (2026-09-26).** An earlier draft of this plan claimed "the
retention default is untested". **That claim was false and is withdrawn.** Verification found
`tests/test_audio_retention_policy.py` (113 lines) already pins four cases: `BILI_KEEP_AUDIO=1` retains,
**unset defaults to retain**, `BILI_KEEP_AUDIO=0` deletes, and `RunCoordinator` honours the policy. Likewise
`tests/test_audio_reclaim.py` (189 lines, 11 cases) already covers the m4a delete, the subtitle-only no-op,
the bare-bvid fallback, path traversal, absolute-path escape, symlink escape, a name-swap race, and the
coordinator's archive-stage reclaim. This task is what survived that verification: **two** real gaps, not a
defect hunt.

**Split point:** This task is XS; if either gap turns out to need a production change rather than a test,
stop and report — a reclaim behaviour change is riskier than a pin and deserves its own dispatch.

**Files:**
- Test: `bilibili-asr-archive/tests/test_audio_retention_policy.py` — the flag-precedence gap (gap 1)
- Test: `bilibili-asr-archive/tests/test_audio_reclaim.py` — the sibling-page scenario (gap 2)
- Modify (only if a test proves a defect): `bilibili-asr-archive/src/bili_asr/audio_reclaim.py`
  (`_candidate_paths`, `:23-49`)
- Out of scope: changing `KEEP_AUDIO_DEFAULT`; adding the flag pair to the fifteen commands that lack it;
  `asr.py`; re-testing anything the two existing suites already pin.

**Interfaces:**
- Consumes: `resolve_keep_audio` (`artifact_root.py:186-197`), `reclaim_audio` (`audio_reclaim.py:64`),
  `_candidate_paths` (`:23-49`), `archive_stem` (`archive.py:34-38`).
- Produces: two tests; no new production interface unless a gap proves to be a defect.

**Gap 1 — the flag's precedence over the environment is unpinned.** The four existing cases all pass
`resolve_keep_audio(None, ...)`; none passes a non-`None` flag. The shipped rule is *flag wins outright*
(`artifact_root.py:190-191`: `if flag_value is not None: return flag_value`), and that precedence is what an
operator relies on when overriding a `BILI_KEEP_AUDIO=0` shell exported globally.

**Gap 2 — no test places a sibling page's file beside the reclaimed row's.** Every existing reclaim case
uses a single row. `_candidate_paths` derives a second candidate from `archive_stem(entry)`, and
`archive_stem` falls back to the bare `bvid` when `cid` is absent (`archive.py:34-38`) — so a
`work_id`-carrying row with no `cid` derives `audio/<bvid>.<ext>`. No test pins what a reclaim does when a
**sibling** file exists in the same `audio/` directory.

- [ ] **Step 1: Write the two tests**

```python
# tests/test_audio_retention_policy.py — beside test_unset_variable_defaults_to_retain
def test_the_flag_wins_over_the_environment():
    """Precedence, not just the fallback: the flag is first in the chain.

    The shipped rule (``artifact_root.py:190-191``) returns the flag outright
    before reading the mapping at all.  An operator who exports
    ``BILI_KEEP_AUDIO=0`` globally and passes ``--keep-audio`` on one run is
    relying on exactly this line, and no existing case exercises it.
    """
    assert resolve_keep_audio(True, {"BILI_KEEP_AUDIO": "0"}) is True
    assert resolve_keep_audio(False, {"BILI_KEEP_AUDIO": "1"}) is False
```

```python
# tests/test_audio_reclaim.py — beside test_archived_asr_row_m4a_deleted
def test_reclaim_of_one_page_leaves_a_sibling_pages_file(tmp_path):
    """The derived candidate must not reach a file a sibling page owns.

    Two rows of one video: ``BV1sib.p0`` (being archived, file present) and
    ``BV1sib.p1`` (a sibling, file present, not being archived).  The reclaim
    runs for the p0 row only.  Pin what survives.
    """
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "BV1sib.p0.m4a").write_bytes(b"x" * 16)
    (audio / "BV1sib.p1.m4a").write_bytes(b"y" * 16)
    entry = _entry(bvid="BV1sib", work_id="BV1sib:p0", page_index=0, cid=123)

    reclaim_audio(tmp_path, entry, keep=False)

    assert not (audio / "BV1sib.p0.m4a").exists()   # the reclaimed row's own file
    assert (audio / "BV1sib.p1.m4a").exists()        # the sibling's file survives
```

- [ ] **Step 2: Run the two tests — expect PASS**

Run: `python -m pytest tests/test_audio_retention_policy.py tests/test_audio_reclaim.py -v`

**Why this step expects PASS rather than FAIL:** both properties are believed correct today — the flag check
precedes the mapping read (`artifact_root.py:190-191`), and the derived candidate for a page-resolved row is
`audio/<bvid>.p{page}.<ext>`, which cannot name a sibling's file. The value of these tests is regression
protection, not a red-green cycle.

If either is **red**, the premise is wrong: **STOP and report to PM with the observed unlink set.** Gap 2
going red means a reclaim can delete a file another live row still needs, which is a **data-loss defect**;
its fix (possibly "stop deriving the bare-bvid candidate entirely") is a PM-dispatched decision, not an
implementer's improvisation.

- [ ] **Step 3: (only if Step 2 was red) Minimal fix** — narrow `_candidate_paths` so the derived candidate
  is emitted only when `archive_stem(entry)` actually differs from the bare `bvid`, and re-run.

- [ ] **Step 4: Run the same selectors — expect PASS.**

- [ ] **Step 5: Commit**

## Acceptance criteria (compass AC 4-6, made checkable)

Verifiable by a reader who never saw the investigation. Run every command from `bilibili-asr-archive/`; every
fixture is offline, and "a download" means the `download-audio` path over the fake upstream seam.

| # | Compass AC | Check | Expected |
|---|---|---|---|
| 4 | AC 4 — `SELECT COUNT(*) FROM audio_objects` is non-zero after a download, and `part_audio_objects` links each object to its part | `python -m pytest tests/test_audio_inventory.py -v`, then on the test root: `sqlite3 <root>/archive.db "SELECT COUNT(*) FROM audio_objects; SELECT COUNT(*) FROM part_audio_objects"` | both counts are non-zero and equal for a one-file download; `audio_objects.format` is the suffix without its dot (`m4a`, or `flac` where ffmpeg is unavailable); `byte_size` equals `os.path.getsize` of the file the manifest names |
| 5 | AC 5 — the flag's precedence over `BILI_KEEP_AUDIO` is pinned, and a reclaim of one page leaves a sibling page's file present | `python -m pytest tests/test_audio_retention_policy.py tests/test_audio_reclaim.py -v` | **both tests pass on first run** — these are characterisation tests of shipped behaviour, so a red result is **not** a task to weaken: Step 2's STOP applies (a red sibling-page case is a data-loss defect and goes to PM with the observed unlink set). No assertion in either existing suite may be relaxed to make them green |
| 6 | AC 6 — `derive-audio-inventory` reports `recorded` / `already` / `missing` / `unlinked` and exits 0 on a zero-row reconciliation | run the command against a root whose manifest names no audio; then against a root with one downloaded file (`python -m pytest tests/test_audio_inventory.py -k derivation -v` covers both) | the one summary line prints all four counters; a root with no work exits **0**, not 1; a named-but-absent file increments `missing` and is **reported, never invented and never deleted** |

Explicitly **not** claimed here, and not gradable as an acceptance criterion: that this iteration adds audio
persistence (compass D6 — it is already the default), that it adds retention tests (four and eleven already
exist; this adds two narrow ones), that `derive-audio-inventory` deletes anything (it is additive and
read-only over the audio tree), and that `storage_key` is an absolute path — it is the root-relative declared
string, **ruled 2026-09-26 as compass D14** (the plan's `AQ1`, now closed).

## Verification plan

| Task | Gate | Expected |
|---|---|---|
| 1 | `python -m pytest tests/test_audio_inventory.py tests/test_storage_schema.py -v` | one `audio_objects` row and one link per download; the schema pin passes and the `audio_objects` / `part_audio_objects` entries are untouched (a sibling table's new map entry from the metadata plan is expected, not drift — see Step 4) |
| 2 | `python -m pytest tests/test_audio_inventory.py -v` | recorded / already / missing / unlinked counted; a named-but-absent row is reported, not invented |
| 3 | `python -m pytest tests/test_audio_retention_policy.py tests/test_audio_reclaim.py -v` | the flag-precedence case passes; a reclaimed p0 row leaves its p1 sibling's file in place (or the defect is reported and fixed) |

Not a gate here: a local full-suite run; a real-corpus run; any device/CLI E2E (a separately requested
`mstar-e2e` workflow).

## Done criteria

- [ ] `SELECT COUNT(*) FROM audio_objects` is non-zero after a download, and equals the number of distinct
      audio files that download produced
- [ ] `part_audio_objects` links each recorded object to the `video_part_id` the manifest row names
- [ ] `record_audio_object` is idempotent on `sha256` (a repeat returns the same `audio_id`, no new row), and
      `audio_objects.sha256` is filled on every row the plan writes — the column is `NOT NULL UNIQUE`, so a
      row without a real digest would be a lie the schema cannot even hold
- [ ] `record_audio_object` also satisfies the table's **second** unique constraint: the same `storage_key`
      observed with a **new** digest updates that row in place (same `audio_id`, refreshed `sha256` and
      `byte_size`), leaving its `part_audio_objects` link intact — never a delete-and-reinsert, which the
      `ON DELETE RESTRICT` foreign key refuses
- [ ] `storage_key` holds the root-relative declared string (`audio/<stem>.<ext>`) on every row — compass
      **D14**; no row carries an absolute path or a base, so a row stays valid across an artifact-root change
- [ ] `derive-audio-inventory` exits 0 on a zero-row reconciliation and prints its one summary line with all
      four counters, whose meanings match `specs/audio-retention-contract.md` §3.1 (not merely the names)
- [ ] The flag's precedence over `BILI_KEEP_AUDIO` is pinned by a test that fails if the flag is ignored
- [ ] A reclaim of one page leaves a sibling page's file present (pinned, or the defect reported)
- [ ] No existing assertion in `tests/test_audio_retention_policy.py` or `tests/test_audio_reclaim.py` was
      relaxed, deleted or reordered to make Task 3's two new cases pass — the eleven and four existing cases
      still pin what they pinned (compass D6: this plan adds two pins, it does not rewrite the surface)
- [ ] `test_schema_inspection_matches_the_declared_contract` passes with **no** change to
      `EXPECTED_TABLE_COLUMNS`
- [ ] `git diff --check -- <in-scope files>` exits 0 and no file outside the task lists changed

## Drift check

Written against `9d530cd`. Before Task 1, run:

```
git diff --stat 9d530cd..HEAD -- \
  bilibili-asr-archive/src/bili_asr/storage/ \
  bilibili-asr-archive/src/bili_asr/services/ \
  bilibili-asr-archive/src/bili_asr/audio.py \
  bilibili-asr-archive/src/bili_asr/audio_reclaim.py \
  bilibili-asr-archive/src/bili_asr/artifact_root.py \
  bilibili-asr-archive/src/bili_asr/cli.py
```

**This check is load-bearing for this plan**: a live session was editing `asr.py` and the test seam on
2026-09-26 (`0a95035`, `83ba8d0`). If `artifact_root.py`, `audio.py` or `audio_reclaim.py` moved, re-read
every `## Current state` line against live code before proceeding. On mismatch → STOP.

## Open questions (owned, non-blocking)

Plan-local numbering, deliberately **not** the compass's: the compass `Q1`/`Q2` are settled (D11/D12) and the
compass `Q3` is a different question. These three are this plan's own and none of them blocks the plan.

| # | Question | Owner |
|---|---|---|
| `~~AQ1~~` | Should `storage_key` store the root-relative declared string (this plan's choice) or an absolute path? **Ruled by the architect review 2026-09-26: the root-relative declared string — compass D14.** An absolute path would write a base durably (against the artifact-root contract's **D12**), need a new resolution rule or a baked-in base (against **D8**), be refused outright by `path_policy._audio_parts` (`:16-29`), and split one logical object across two rows under two roots, against `sha256`'s role as the identity. The ruling also corrected this task's writer: with `sha256` and `storage_key` both `UNIQUE`, the `ON CONFLICT(sha256) DO NOTHING` shape raises on a same-name/new-bytes observation — the one failure this task's non-fatal rule would have swallowed. See Task 1 Step 3. | architect — **closed** |
| AQ2 | Is a second full copy of each audio file under `$TMPDIR` acceptable (the `asr.py:304-318` materialize path)? It is invisible to the store and doubles transient disk per row. It is out of scope here only because `asr.py` is under concurrent edit. | architect |
| AQ3 | Should the fifteen commands without `--keep-audio` gain it, or is the flag's absence from them the correct signal that they cannot reclaim? Today's answer is the latter; it should be written down rather than assumed. | PM |

## Fix round (2026-09-28) — the L2 review's 9 Important findings

Recorded here because the review landed **after** the Phase 3 close commit, so this is a post-close fix
round rather than a task step.

- Review: `{SDD_DIR}/20260926-audio-inventory/task-2-review.md` — `Needs fixes`, 0 Critical / 9 Important /
  4 Minor. Dispatched as A-R4; it was fulfilled (the seat survived this time) and is closed.
- Fix brief: `{SDD_DIR}/20260926-audio-inventory/task-2-fix-brief.md`.
- The Phase 4 PR (#25) was opened and its **merge stopped**: the PM had begun a `--no-commit` merge of
  `origin/main` into the integration branch, saw the review land, and aborted it (integration back to
  `3a5b638`, clean). The trial merge was itself clean and the merged tree ran 1767 passed / 125 skipped —
  the blocker is the findings, not a conflict.
- Rulings made before any code changed: **F6** reads the authoritative `video_parts.duration_ms` from the
  store (the manifest's `duration_s` is lossy — floor + a clamp to 1); **F5** adds the command to
  `_ARCHIVE_WRITER_COMMANDS`; **F2** compares `byte_size` via a `stat`, never by reading bytes, so the
  published cost model survives; **F3** gives `--deep` a test whose mutant goes red; **F4** bounds the error
  path and still prints the summary; **F1c** moves the print out of the service layer; **F7** keys the
  recorded `storage_key` to the path actually resolved on disk; **F8** makes the counters converge; **F9**
  writes the byte-snapshot fixture the commit message claimed.
- Residuals: **A-R5** (the 9 findings), **A-R6** (the close was committed one step ahead of this review —
  a recurrence of what `best-practices/completion-claims-need-live-evidence.md` describes, this time by the
  PM).

## Engine lifecycle

- **Scoped sequence** — coordinator-only, one verb per transition: `bind --coordinator` → `prepare` →
  `bind` → `progress` → `handoff` → `accept` → `integration-start` → Git merge → `integration-accept` →
  `complete`. No implementer or reviewer edits a snapshot row.
- **Evidence order** — compound disposition, PR identity and merge evidence are recorded **after** the row
  is `Done`.
- **Precondition** — not dispatchable while iteration `iter-2026-09-metadata-audio-layout` is unregistered
  and `iter-2026-09-qwen3-asr-closeout` still holds its execution lease.
