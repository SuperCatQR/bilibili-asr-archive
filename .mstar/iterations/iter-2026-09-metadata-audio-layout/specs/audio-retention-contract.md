# Audio retention contract

**Iteration:** `iter-2026-09-metadata-audio-layout` (registered `active` 2026-09-26; awaiting `locked`).
**Plan:** `20260926-audio-inventory`.
**Status:** draft spec — to be locked by the Phase-1 review chain when the iteration locks.
**Baseline:** `9d530cd`, 2026-09-26.

The operator requirement that produced this contract: *"流水线过程中下载的音频文件应当持久化的保存"* —
audio downloaded during the pipeline should be persistently saved.

**The investigation's first finding is that this is already the code's behaviour.** `KEEP_AUDIO_DEFAULT` is
`True` (`artifact_root.py:87`), reclaim runs only when the resolved policy asks for it
(`audio_reclaim.py:64-66`), and no code path hard-codes a reclaim. So this contract does **not** restate a
policy that does not exist. It records what is true, names the two holes that *are* real, and bounds what a
future change may do to the retention default.

## 1. The retention chain, as shipped

| Stage | Behaviour | Anchor |
|---|---|---|
| Write target | `{artifact-root}/audio/{bvid}.p{page}.m4a`, or `.flac` when ffmpeg is unavailable | `audio.py:229-260` |
| Staging | `.audio-stage-<32 hex>.<suffix>`, created `O_EXCL`/`O_NOFOLLOW` mode `0600`, `os.replace`d into place | `audio.py:90`, `:108-121`, `:247-259` |
| Durability | `os.fsync` on the file descriptors and the `audio/` directory before the row is written | `audio.py:236`, `:247`, `:263` |
| Manifest transition | `_mark_audio_ok` records `status: audio_ok` + the **root-relative** `audio_path`, re-confined at that base | `audio.py:186-260` |
| Reclaim trigger | `_reclaim_after_archive` — called by the five archiving commands only | `cli.py:2341-2360`; call sites `:2275`, `:2377`, `:2487`, `:2624`, `:2659`, `:3011`, `:3204` |
| Policy resolution | flag → `BILI_KEEP_AUDIO` (`"1"` retains, `"0"` reclaims) → `KEEP_AUDIO_DEFAULT = True` | `resolve_keep_audio`, `artifact_root.py:186-197` |
| One resolution point | `cli.main` resolves once, so every command sees a concrete bool, never `None` | `cli.py:3747-3748` |
| Reclaim mechanics | validates the name through `unlink_confined_audio` (quarantine → `fstat` identity check → unlink), under **both** bases | `audio_reclaim.py:64-105`, `path_policy.py:167-179` |
| Flag pair carried by | `asr`, `pilot`, `run`, `schedule`, `campaign` — exactly the five that can archive | `cli.py:157`, `:185`, `:351`, `:399`, `:445` |

**Retention is the default. Reclaim is opt-in, twice over** (an explicit `--no-keep-audio` or
`BILI_KEEP_AUDIO=0`, *and* a command that actually archives).

## 2. The real gaps

### 2.1 The audio inventory is not queryable

`audio_objects` and `part_audio_objects` were declared in `schema.sql:92-110` as the "reserved structured
media boundary … intentionally empty in the metadata plan". They are still empty: **no module in `src/`
reads or writes either table** (verified by grep — the only `INSERT`s live in
`tests/test_storage_schema.py:710-775`). `transcripts.model_id` is hard-wired `NULL`
(`database.py:913-923`), so the third reserved table `asr_models` is never populated either.

Consequence: "which audio do I have?" is answerable only by reading `manifest/manifest.jsonl` and `ls`-ing
`audio/`, then reconciling the two by hand. The store — the surface `status`, `runs` and
`publish-transcripts` already read — cannot answer it.

**This is the gap the plan closes**, and the larger half of its work.

### 2.2 Two narrow coverage holes in the retention and reclaim tests

**Corrected 2026-09-26 during plan authoring.** An earlier draft of the audio plan asserted "the retention
default is untested". **That claim was false and is withdrawn** — it was made without opening the test
files, and opening them showed substantial coverage:

| Suite | Lines | Already pinned |
|---|---|---|
| `tests/test_audio_retention_policy.py` | 113 | `BILI_KEEP_AUDIO=1` retains · **unset defaults to retain** · `=0` deletes · `RunCoordinator` honours the value after a row is archived |
| `tests/test_audio_reclaim.py` | 189, 11 cases | m4a delete · subtitle-only no-op · bare-bvid fallback · path traversal · absolute-path escape · in-`audio/` reclaim · `.flac` candidate · symlink escape · name-swap race · coordinator archive-stage reclaim |

What genuinely remains unpinned, and is the whole of the plan's retention half:

1. **Flag precedence.** Every existing retention case passes `resolve_keep_audio(None, ...)`; none passes a
   non-`None` flag. The shipped rule is *flag wins outright* (`artifact_root.py:190-191`) — the line an
   operator relies on when overriding a globally exported `BILI_KEEP_AUDIO=0`.
2. **The sibling-page scenario.** Every existing reclaim case uses a single row; none places a sibling page's
   file in the same `audio/` directory while one row is reclaimed, so the derived candidate's blast radius
   is unpinned.

**Method note for future readers:** this correction is the `claim-scope-discipline` class
(`{KNOWLEDGE_DIR}/best-practices/claim-scope-discipline.md`) — a claim about what a codebase *lacks* must be
checked against the codebase, not inferred from the absence of a symbol in one grep. Two greps
(`grep -rn 'KEEP_AUDIO_DEFAULT' src/`, `grep -rn 'keep_audio' tests/ | head`) would have prevented it. The
same discipline caught the plan's other premise errors: `bin` absence, `test_audio_retention_policy.py`'s
existence, and the `_candidate_paths` shape.

## 3. Inventory field semantics

| Field | Rule |
|---|---|
| `audio_objects.sha256` | Identity. A re-download of byte-identical audio is **one** object; recording it twice returns the same `audio_id`. **Both `sha256` and `storage_key` are `UNIQUE` (`schema.sql:94`, `:98`)**, so a writer that conflicts on `sha256` alone is wrong: the same **name** holding **new bytes** must refresh that row **in place** (`UPDATE ... WHERE storage_key = ?`), never delete-and-reinsert — the `part_audio_objects` foreign key is `ON DELETE RESTRICT` and refuses the delete. One row per declared key, its digest always the last observation's |
| `audio_objects.storage_key` | The **root-relative declared string** the manifest already records (`audio/<stem>.m4a`), so the two surfaces cannot disagree about which file a row names. Not an absolute path — **ruled 2026-09-26 (compass D14); the absolute alternative is refused, not merely dispreferred.** An absolute key would write a root durably (against the artifact-root contract's **D12**, which records the root nowhere), need its own resolution rule or a baked-in base (against **D8**'s ordered-base pair), be rejected outright by `path_policy._audio_parts` (`:16-29`, which refuses any absolute path), and split one logical object into two rows once observed under a second root — against `sha256`'s role as the identity. No row ever carries a base, so a row stays valid across an artifact-root change |
| `audio_objects.byte_size` | The on-disk size at observation |
| `audio_objects.format` | The suffix without its dot (`m4a`, `flac`) |
| `audio_objects.duration_ms` | The part's duration as the store already knows it. `0` is permitted by the schema (`CHECK (duration_ms >= 0)`) and means "unknown", not "empty" — a reader that needs a real duration reads the part's, and a `0` here is never rendered as a zero-length item |
| `part_audio_objects.acquisition_source` | A bounded scalar naming the route that produced it (e.g. `download-audio`). Free-form prose is not allowed |
| `part_audio_objects.video_part_id` | The store's own part id — resolved from `(bvid, page_index)`, never from a filename |

**Both tables already exist and are pinned** by `BASE_TABLES` / `EXPECTED_TABLE_COLUMNS`
(`tests/test_storage_schema.py:47` and `:69`) plus
`test_schema_inspection_matches_the_declared_contract` (`:856-942`), which reads **four** per-table maps
(`EXPECTED_TABLE_COLUMNS`, `EXPECTED_FOREIGN_KEYS` `:173`, `EXPECTED_PRIMARY_KEY_INDEXES` `:205`, plus
`EXPECTED_UNIQUE_CONSTRAINTS` `:198` and `EXPECTED_INDEXES` `:215`). Their columns are therefore **fixed**:
no addition, rename or drop. That is not a limitation here — it is why this plan needs no schema change at
all, and why it does not cost an operator an `archive.db` rebuild (§2 of the metadata contract).

**The sibling plan edits the same test file, and that is expected.** `20260926-video-metadata-enrichment`
adds `video_tags` and `video_details` and therefore adds entries to those maps for **its** tables (D3). No
schema object is shared between the two plans (D3 vs D7), but a reader comparing the whole of
`tests/test_storage_schema.py` across the iteration will see a diff that is not drift. What this plan
guarantees is narrower: the `audio_objects` / `part_audio_objects` entries — including
`EXPECTED_UNIQUE_CONSTRAINTS["audio_objects"] == (("sha256",), ("storage_key",))` at `:201` — are untouched.

### 3.1 The reconciliation vocabulary (product definitions, ruled 2026-09-26; `recorded`/`missing` amended 2026-10-04)

`derive-audio-inventory` prints one summary line. Its four counters are defined here so the command's output
is a contract rather than a naming exercise, and so the acceptance criterion that reads them (compass AC 6)
can be checked by a reader who did not write the command:

| Counter | Counts | Never |
|---|---|---|
| `recorded` | a manifest candidate this run **wrote the content of** — either it had **no** `audio_objects` row, or it had a row that **did not match** (same declared `storage_key`, different bytes: the file was replaced in place, and the row is refreshed rather than appended) | never invented when the file was absent |
| `already` | a candidate whose object row was already present and matched — a re-run converges, it does not accumulate | never a second row for one `sha256` |
| `missing` | a manifest row that **names** an `audio_path` and the file is **not there** — a named path that resolves nowhere (the shipped reclaim path, or a manual delete) | never a present-but-unreadable file (see below); never deleted, never re-created, never silently dropped from the report |
| `unlinked` | an observed audio object that **no** `part_audio_objects` row attributes to a part — the store can see the file but not tie it to a work | never used to delete an unattributed file |

**A present-but-unreadable file is reported by name, and it is not a fifth counter** (ruled 2026-10-04,
`I-000044`). `reconcile_audio_inventory` appends such a `storage_key` to the outcome's `unreadable` tuple
(`audio_inventory.py:222`, `:236`, `:259`) — the `except OSError` arms around `stat`/digest reads — and the
command prints each one on **stderr** as `derive-audio-inventory: unreadable: {storage_key}`
(`cli/queue.py:230-234`). It is excluded from `missing` by definition: `missing` is "names a path that is not
there" and increments only when a named `audio_path` resolves nowhere (`:212`), while an unreadable file *is*
there. It is also not `recorded`: `sha256` is `NOT NULL UNIQUE`, so a row without a digest cannot be
deduplicated and must not be written. Naming the rows separately is what keeps the summary line from reading
smaller than the tree without redefining a counter this section owns (`AudioInventoryOutcome` docstring,
`:73-80`). **No counter changes; the table's `Never` column stays honest.**

**`recorded` covers the row-exists-but-does-not-match case** (ruled 2026-10-04, `I-000050` — settled, not
flagged). The wording above it read "a manifest candidate that had **no** `audio_objects` row and now has
one", which covered only the common case. The code has always counted the second case as `recorded`, because
this run wrote the object's content afresh: calling it `already` would assert the *and matched* the same
section requires of that counter, and counting it as neither would hide a rewrite. The next unchanged run
finds a matching row and reports `already`, which is the convergence the counter pair exists to give. The
code comment at `audio_inventory.py:283-292` names this as residual **A-R7**; this amendment **settles it** —
the contract now states the behaviour the code already has, and A-R7 no longer needs a ruling.

`--deep` re-verifies the digest of an object whose row is already present; it is **not** a "hash or don't"
switch, because `audio_objects.sha256` is `NOT NULL UNIQUE` (`schema.sql:94`) and a row without it cannot be
deduplicated. The command is additive and read-only over the audio tree: no counter authorises a write to
the filesystem.

## 4. What a reclaim may and may not delete

- A reclaim may unlink **only** names that (a) resolve through `unlink_confined_audio` at a base that holds
  an `audio/` directory, and (b) belong to the row being archived.
- The candidate set is `_candidate_paths(entry)` (`audio_reclaim.py:23-49`): the row's recorded `audio_path`
  first, then `audio/<stem>.<ext>` where `stem` is `archive_stem(entry)` when the row carries `work_id` and
  is not `unresolved`, **else the bare `bvid`**. Note that `archive_stem` itself falls back to the bare bvid
  when `cid` is absent (`archive.py:34-38`), so a `work_id`-carrying row can still derive a bare-bvid
  candidate.
- **Owning a name is not the same as owning the bytes behind it.** A bare-bvid candidate could in principle
  name a file a sibling page's row still needs. The plan pins the observable candidate set per row shape so
  this cannot widen silently; if the pin exposes over-deletion, that is a **data-loss defect** and stops the
  task pending a PM decision (§Task 3 Step 2 of the plan).
- A reclaim is **non-fatal by design**: `_reclaim_after_archive` swallows `OSError`/`ValueError`
  (`cli.py:2341-2360`) because the transcripts already exist and the row stays `archived`. A failed reclaim
  leaves the file; that is the safe direction.

## 5. Bounds on a future change

- `KEEP_AUDIO_DEFAULT` may not be flipped to `False` without a recorded decision and a plan that migrates
  the operator's expectations; the constant is the last line of defence for data that cannot be re-derived
  without re-downloading.
- The fifteen commands without `--keep-audio` (`fetch-meta`, `status`, `runs`, `probe-subs`, `harvest-subs`,
  `download-audio`, `derive-manifest`, `publish-transcripts`, `search`, `coverage`, `verify`, `recover`,
  `evaluate-concurrency`, `export`, `check-asr-env`) must not gain a reclaim path incidentally. Today they
  cannot reclaim because they never call `_reclaim_after_archive`; that is a structural property and should
  stay one.
- Audio already reclaimed cannot be restored. Nothing in this contract implies otherwise, and no command
  should promise it.

## 6. Recorded but out of scope: the transient second copy

`ASRRunner.transcribe` always receives a `/proc/self/fd/N` path, because the chain wraps every call in
`confined_audio_file` (`cli.py:2261`, `:2467`; `coordinator.py:579`). `_materialize_input`
(`asr.py:304-318`) therefore copies the **entire** audio file into `$TMPDIR` on every row and unlinks it in
the `finally` (`:793-798`).

Measured: a 47-minute item is ≈ 47 × 60 × 8 000 ≈ **23 MB** at a 64 kbps m4a, and the materialized copy is a
decoded PCM `.wav` of the same duration — far larger than the compressed source, written to and deleted from
the system temp filesystem per row. The per-chunk scratch (`asr.py:767`, `bili-asr-chunk-*.wav`) adds one
short WAV reused across chunks, which is bounded and fine.

This is a real cost and it is **invisible to the store**. It is out of this plan's scope only because
`asr.py` was under concurrent edit by another live session on 2026-09-26 (`0a95035`, `83ba8d0`), and because
the honest fix — reading the confined descriptor in place instead of materializing — changes an audio-decode
path that deserves its own plan and its own evidence. It is recorded here so the next reader does not
re-derive it.
