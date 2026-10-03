# Issue Register — _default project

> 本文档由 `.mstar/store.db` 的 `issues` 表导出，是**只读镜像**，不是真相源。
> 真相源是 store.db 本体（`mstar issue list` 读取的对象）；本文档存在的唯一理由是
> store.db 按 `.gitignore` 约定留在本机（进程权威，不入 git），而 issue 的登记内容
> 需要在 worktree 和 push 中可见。**任何时刻两者不一致，以 store.db 为准。**
> 重新生成：见 `bilibili-asr-archive/scripts/` 或手动从 store.db 导出。

## 统计

- 总计：211 条
- open：175 条（high 15，medium 61，low 99）
- resolved：34 条；waived：2 条

---

## Open issues（按严重度排序，共 175 条）

### I-000039 [high] (review-obligation)

****The 123pan WebDAV mount failed authentication, and a re-seed of the T5 arms destroyed the staged audio for the frozen six-item corpus (C6).** On 2026-09-26 the mount began answering every READ with `401 Unauthorized` while directory listings still succeeded from cache, so it looked healthy. Running `ab-hotwords-qwen3.sh setup` with `ITEM_ORDER=shortest-first` re-seeded the arms; `setup` began with `rm -rf $AB` and then copied from `/mnt/123pan/.../audio`, which failed with `EIO`. The previous arms' audio was already deleted, so five of the six C6 items (`BV1iddQYQE7D`, `BV1BdtazGEBE`, `BV1vNTqzFEve`, `BV1Y7M4zNEfF`, `BV11p5qzAE6s`) and two of three arms of `BV1zz5zzFENq` were lost from the target host. An exhaustive search found no copy: `/root`, `/mnt/e/asr-archive-20` (20 unrelated items), the control host, and the rclone VFS cache (8 KB) all lack them. The only other copy was on 123pan, behind the failing auth.**

- **Impact**：T5's ability to reach the P1–P9 verdict at all: the frozen six are the only instrument that can settle P1/P2, and their audio is no longer locally available. Also a process lesson, because the failure was avoidable and the driver invited it — `setup` deleted before it verified its source, and the operator ran it while already knowing the mount was unreadable.
- **Acceptance**：accept
- **Owner**：@project-manager
- **Registered**：2026-09-26
- **Revision**：1

### I-000041 [high] (review-obligation)

**A dead `SESSDATA` makes the caption channel return an empty inventory, and that emptiness is recorded as `no-subtitle` — a durable false negative that `credential_present` cannot flag, because it records presence, not validity.**

- **Impact**：`src/bili_asr/services/subtitle_ingest.py`'s outcome mapping (an empty track inventory maps to `no-subtitle`, never to `failed`) together with the evidence column that mapping writes, `acquisition_runs.credential_present` (`storage/schema-transcripts.sql`), and the rule `{KNOWLEDGE_DIR}/architecture-patterns/subtitle-acquisition-contract.md` states: login-gated tracks 'become visible through the credential in effect (the SESSDATA cookie), not through a request flag'. A present-but-expired credential is stored as `credential_present=1` beside `outcome='no-subtitle'` — the one combination a later reader would take as 'an authenticated probe found nothing'. Nothing under `src/` probes validity: `NAV_URL` is used only to fetch the WBI key pair (`bili_client.py:394-404`), and it actively tolerates the logged-out answer through `accept_codes={-101}`. Consequence: the caption backlog can fill with false negatives that rotate to the back of `v_pending_subtitles` indefinitely, each indistinguishable from a genuinely caption-less part.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-25
- **Revision**：1

### I-000067 [high] (review-obligation)

**F7: the ASR stage writes its archive bundle but records NO `transcripts` row in `archive.db`, so `v_missing_transcript` keeps listing parts already transcribed and `pipeline_state` reads `audio_ok` for an archived part. A naive re-run re-selects the work and pays the GPU again.**

- **Impact**：`src/bili_asr/cli/asr.py` / the archive stage: the transcript artifact is written but no `transcripts` row is recorded, so `v_missing_transcript` (which requires audio evidence AND no stored transcript) never drops the part. Two tests assert the intended behaviour: `tests/test_cli_queue_source.py::test_asr_store_source_selects_transcript_gap_part` and `::test_pilot_store_source_uses_gap_views`.
- **Acceptance**：accept
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000136 [high] (review-obligation)

****Any lock regeneration for this project silently pulls a PyPI CUDA torch, because `accelerate` requires `torch` with no marker — and `uv sync` would then replace the verified `repo.radeon.com` ROCm build on the one host every GPU result comes from.** `pyproject.toml` deliberately does not declare torch and says so in a NOTE, but a NOTE constrains nothing a resolver reads: `accelerate>=1.0` is in the `[asr]` extra, so a resolution materialises torch and its whole NVIDIA closure.**

- **Impact**：Any `uv lock` / `uv sync` invocation against this project, and therefore the documented `uv sync` install path. `pip install -e ".[asr]"` is unaffected in the sense that it does not touch the lock, but it has the same resolver behaviour with respect to `accelerate`'s torch.
- **Acceptance**：accept
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000149 [high] (bug)

**006 attempt-ledger in-memory map: cross-process attempt numbering + strict malformed-history check lost (2 regressions)**

- **Impact**：Two fresh processes appending the same (work_id,stage) key both write attempt=1 (cross-process safety lost); appending to a malformed attempts.jsonl no longer raises. Broke 2 pre-existing test contracts.
- **Acceptance**：Restore cross-process-safe attempt numbering under the flock (re-read the tail on collision) AND the strict malformed-history raise at append, while keeping the O(1) batch perf for the single-writer case; the 2 persistence_scale tests go green
- **Owner**：project-manager
- **Registered**：2026-10-01T23:34:01.967Z
- **Revision**：1

### I-000164 [high] (bug)

**AUDIT-2026-10-02R2: manifest journal replay splits on str.splitlines(), so one U+2028/2029/0085 in a row truncates the replay and the next rewrite drops every later row**

- **Impact**：A single legal-but-unusual separator character inside any journaled row (titles come from upstream) makes ManifestStore.load()/upsert() stop at that row for the instance's lifetime; the truncated view is what save()/compact()/migrate_legacy_rows() write back, so later rows are durably deleted from the append-only SSOT while the sibling newline-based readers still see them.
- **Acceptance**：The journal replay splits on "\n" only (mirroring coordinator._replay_lines, which documents this exact hazard); a regression test journals a row carrying U+2028 followed by a later row and asserts both replay and survive a save().
- **Registered**：2026-10-02T14:51:58.452Z
- **Revision**：1

### I-000165 [high] (bug)

**AUDIT-2026-10-02R2: caption write-back runs inside the archive success guard, so a store-shape failure mislabels an already-published bundle `archive: failed` and skips `_mark_archived`**

- **Impact**：write_archive() publishes all four artifacts, then the caption write-back raises inside the same try; the row is recorded failed, `_mark_archived` is skipped, and the operator is shown a failure for a complete archive. A rerun republishes the same bundle. The ASR route deliberately places its write-back outside the guard; the caption route does not.
- **Acceptance**：The caption write-back runs after the `archive: ok` record (mirroring _stage_asr_archive), and a regression test proves a write-back that raises still leaves the row `archive: ok` with the manifest row archived.
- **Registered**：2026-10-02T14:52:15.929Z
- **Revision**：1

### I-000166 [high] (bug)

**AUDIT-2026-10-02R2: QueueSource.ensure_asr_run mints run_id = f"{command}-{int(time.time())}" against a PRIMARY KEY and swallows the collision, silently disabling every transcript write-back in that invocation**

- **Impact**：acquisition_runs.run_id is TEXT PRIMARY KEY and start_acquisition_run raises sqlite3.IntegrityError on a duplicate; ensure_asr_run wraps it in `except Exception: self.asr_run_id = None`. Two same-second runs of the same command — including the in-process per-batch reopen of the write-back source, which closes the source (and its asr_run_id) at every batch boundary — collide, and the whole run's `transcripts` rows are skipped silently. This re-enters the R14/v_missing_transcript gap at one-second granularity; the operator sees a successful archive.
- **Acceptance**：The generated run id is unique per invocation (monotonic suffix or uuid), or the collision is retried; a test proves two runs of the same command inside one wall-clock second each record their transcript row.
- **Registered**：2026-10-02T14:52:32.120Z
- **Revision**：1

### I-000187 [high] (bug)

**An empty caption inventory is recorded as a durable no-subtitle even when the credential is live: probe-subs and harvest-subs disagree on the same part, minutes apart, and the emptiness is what admits the paid audio->GPU-ASR branch**

- **Impact**：The same part answered tracks=0 at 07:52 and tracks=1 minutes later, with nothing changed but time; harvest-subs in between stored its subtitle-ai body and recorded no-subtitle=0. Because v_missing_audio admits a part only on a newest no-subtitle/failed attempt plus absent audio, a transient empty inventory is the admission ticket to the paid branch (download + GPU ASR). The gateway's own contract states the confusion out loud: 'An inventory the credential in effect could not see is an empty tuple - never a not_found failure'. So 'no subtitles exist' and 'this call did not see them' collapse to tracks=0, and only the first is safe to treat as exhaustion. This run paid GPU time on one such part before the discrepancy surfaced. It is the same family as I-000041 (dead SESSDATA -> empty inventory -> durable no-subtitle) but strictly broader: I-000041 attributes the emptiness to an invalid credential, while this was measured with a valid one, so fixing I-000041 alone would not close this.
- **Acceptance**：Either the emptiness is no longer treated as proof of exhaustion (a part whose inventory is empty but unverified stays unexhausted), or the observation is recorded distinguishably (e.g. an unverified/transient error_code alongside the attempt) so a single empty inventory cannot durably mark a part caption-less; probe and harvest agree on the same part at the same moment. A regression test pins the disagreement case.
- **Registered**：2026-10-03T00:17:31.279Z
- **Revision**：1

### I-000188 [high] (bug)

**The ASR stage can store a transcript that silently covers only part of the audio's speech, and the archive records it as success: 13 segments spanning 0-59.0 s of a 73.56 s recording, 20% of the speech unreached, with no coverage signal anywhere**

- **Impact**：A transcript that is missing a fifth of the recording is indistinguishable from a complete one: same `stored` attempt outcome, same `archived` bundle, same four-family publication, no error_code, no warning. Anything downstream that treats the transcript as the video's words is wrong for that span - search misses it, the proofread side-by-side reports it as unassigned captions, and an operator has no reason to look. Measured on a real part, reproduced on a fresh full-length download, and NOT caused by the token budget (4x budget produced byte-identical output). The only mechanism in the product that detected it at all is proofread Guard A, which is opt-in, requires two routes, and runs downstream of publication.
- **Acceptance**：An ASR run either covers the decoded audio's speech or says so: the stored transcript carries a coverage signal (span/chars against decoded duration, or an explicit uncovered-tail marker) that is visible in the store and in the bundle, and a run whose coverage falls materially short is not silently recorded as a plain success. A regression test pins a short-coverage decode against a full-length input.
- **Registered**：2026-10-03T00:42:32.140Z
- **Revision**：1

### I-000190 [high] (bug)

**A concurrent workflow-close write clobbers a live workflow's root status.json entry, silently pausing that session's writes (lost update on the shared v2 register)**

- **Impact**：A second session closing its own workflow via `mstar status workflow-close` rewrites the whole `{HARNESS_DIR}/status.json` from a snapshot read before the first session registered, deleting the live workflow's `workflows[]` entry. The affected session is not told: its next engine read reports `workflow.selection.unbound-multi-active` (or an empty register) and its writes pause, while its snapshot and leases stay intact on disk. Recovery is manual and undocumented for this case: `iteration register` refuses with `catalog.registration-conflict` (the operation is already `committed`), and `catalog reconcile` returns `recovered:false` for a committed operation, so the documented re-register path cannot run against this state.
- **Acceptance**：Reproduce: session A registers a workflow (root entry present); session B closes a different workflow and its `status.json` read predates A's registration; after B's write, A's entry is absent from `workflows[]`. Proven this session: `e2e-23191782-store-writeback-chain` closed at 10:27 and `status.json` went from `[iter-2026-10-ledger-integrity, e2e-...]` to `[]`, wiping the live iteration's entry. Fix direction: make the root-register mutation a read-modify-write under the existing `.status-write.lockdir` (re-read inside the lock, drop only the caller's own entry) so a concurrent close cannot delete entries it never read; and/or make `iteration register`'s recovery branch reachable for a committed operation whose root entry is missing. Verified when: two concurrent registrations/closes interleaved leave both live entries present, and the affected session's writes never pause.
- **Registered**：2026-10-03T02:38:49.677Z
- **Revision**：1

### I-000195 [high] (bug)

**migrate_legacy_rows commits a snapshot-only view and then unlinks the journal, durably deleting a journaled supersede of an existing page-qualified row**

- **Impact**：`migrate_legacy_rows` sets its rewrite base to `dict(current)` where `current = self._read_latest()` reads the SNAPSHOT only (`manifest.py:521`, `:528`). Journaled rows are overlaid onto that base only when the key is absent (`:541-543`) or when the snapshot row is bare-legacy (`:536-540`). For a key present in BOTH the snapshot (already page-qualified) and the journal, the newer journal row is discarded; `:596-598` then `_replace_snapshot(next_entries)` + `_remove_journal()`, so the journal — the only copy of that transition — is deleted and every later reader sees the stale snapshot status. This is the same durable-deletion class the iteration set out to close, in the one rewrite path that builds its base from the snapshot instead of the effective replay view, and it contradicts plan journal-replay-integrity's stated invariant ('no rewrite may delete a line the replay never saw' — here the replay DID see the row and the rewrite still deletes it). Reachable from production: `subtitles.harvest_subtitle` calls it (`subtitles.py:109`), from `cli/pilot.py:531` and `coordinator.py:1095`. Pre-existing at base 1e756df, not a regression of any change in this iteration.
- **Acceptance**：A rewrite that unlinks the journal can only do so after every row the replay saw is durably published to the snapshot. Verified when: the QC seat-3 repro (public API only — `save({BV1:p0: meta_ok, BV9: bare legacy})` → `upsert(BV1, status='archived')` → `migrate_legacy_rows(lambda b: [page(b,0,1)])`) leaves the snapshot's `BV1:p0` row at `archived` with the journal unlinked, and a fresh `load()` agrees; plus a regression test pinning the journaled-supersede case for a page-qualified key.
- **Registered**：2026-10-03T06:30:24.784Z
- **Revision**：1

### I-000200 [high] (decision)

**DECISION (operator, 2026-10-03): carry the ASR attestation evidence outside the attempt vocabulary — option 2 — because the existing CHECK rejects every new outcome/error_code value and a schema rebuild is the cost this repo's standing policy exists to avoid**

- **Impact**：The iteration iter-2026-10-asr-success-attestable cannot leave Phase 1 until this is settled, because it is a Blocking=Yes open question (Q6 in the compass) and phase-1-prepare 1.3(v) forbids locking the compass with a blocking row unconverged. The decision also fixes the shape of two plans: it decides where the coverage evidence and the caption-admission distinction live, and therefore what the implementation tasks may and may not touch.
- **Acceptance**：D8/D9/D10 are rewritten to carry their facts outside the acquisition_attempts vocabulary: coverage evidence rides the manifest row (measured to accept unknown keys — validate_manifest_record ends in `return dict(entry)`, manifest.py:105, so no DDL), and the caption-admission distinction gets a non-error_code carrier (e.g. an observation count on the manifest row). No new outcome or error_code value is introduced. The compass Open Questions table's blocking row Q6 is then converged into Decisions with this rationale, and only then may the compass be locked.
- **Registered**：2026-10-03T11:24:10.286Z
- **Revision**：1

### I-000201 [high] (decision)

**DECISION (operator, 2026-10-03): I-000188 is deferred deliberately — the defect stays open and unfixed for now, with its evidence recorded, rather than being fixed outside the iteration that scoped it**

- **Impact**：I-000188 (a transcript covering 0-59.0 s of a 73.561 s recording, 20% of the speech unreached, archived as an unqualified success) remains live in the product. Every ASR run that under-covers its audio is still indistinguishable from a complete one, and the archive's record still says success. The deferral is a recorded operator decision, not an oversight: it must not later be read as 'nobody noticed'.
- **Acceptance**：I-000188 stays disposition=open with its evidence intact. It is worked when the iteration iter-2026-10-asr-success-attestable resumes (its plan asr-coverage-attestation is the vehicle, blocked only on the Q6 carrier decision, now ruled). If that iteration is abandoned before implementation, this row is the trigger to re-scope the defect elsewhere rather than let it lapse. No fix may land outside the plan that owns it.
- **Registered**：2026-10-03T11:24:21.835Z
- **Revision**：1

### I-000207 [high] (bug)

**A peer session's stale write reverts a closed plan row in the workflow snapshot, resurrecting its execution lease and failing the phase gate**

- **Impact**：Second observed occurrence of the lost-update class on the shared v2 registers (the first is `I-000190`, which covers the *root* `status.json` entry being deleted by a peer's `workflow-close`). Here the damage is to the **workflow snapshot**: `journal-compaction-lifecycle` was closed to `Done` with its `execution_lease` released and its merge commit on the integration branch, the compass was set to `completed`, and then a peer session wrote `snapshot.json` from a stale read and restored the row to `InProgress` **with the lease intact**. The iteration phase gate consequently reported `PLAN_NOT_DONE` / `allPlansDone: false` for an iteration whose four plans were all merged and verified. Two properties make this more than cosmetic: (a) the resurrection of an `execution_lease` on an already-merged plan is exactly the state the engine uses to authorise further writes to a worktree whose work is finished, and (b) it is silent — the only reason it was caught is that the phase gate is re-run at close rather than trusted from the earlier success. Both the root register and the snapshot are engine-owned read-modify-write files with no compare-and-set, and the engine's own `.status-write.lockdir` guards only each individual write, not the read that feeds it.
- **Acceptance**：A write to a shared v2 register cannot resurrect a terminal plan row or its lease. Verified when: two sessions writing concurrently cannot leave a `Done` row (or a released lease) reverted to a pre-terminal state — either the write path re-reads under the lock before applying its patch, or it carries a revision/expected-value guard that refuses when the live file moved since the caller's read; and a test reproduces the interleaving (read → peer write → apply) and asserts the terminal row survives.
- **Registered**：2026-10-03T14:43:53.414Z
- **Revision**：1

### I-000023 [medium] (review-obligation)

**A **hard kill** (SIGKILL/SIGTERM/OOM — `_publish_bundle` has no `finally`) inside the publication path leaks the fixed-name staging directory `transcripts/.archive-bundle-stage`, after which **every** later publication into that root fails permanently until an operator removes it; the printed line is `<work_id>: failed (OSError)`, indistinguishable from an unmounted root.**

- **Impact**：`archive.py`'s staging/publication guard (not this plan's diff). The docstring half of the claim **is** this plan's diff and is fix-wave scope (CW-2). **Width note (seat 3, 2026-09-20):** the wedge is not limited to non-unwinding terminations — if the `finally`'s own I/O fails (the trailing `os.rmdir` hitting EIO/ENOTEMPTY, or the final `os.close`), an *unwinding* termination lands in the same state. Any closing condition for this row must cover both paths.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000033 [medium] (review-obligation)

**The root registry is versioned while the documents it points at are not: `.mstar/status.json` is tracked in git, `.mstar/workflows/**` is gitignored, so a workflow registration (and its `dir`) reaches a checkout whose snapshot document never travelled — that checkout then holds a live registry row naming a directory that does not exist.**

- **Impact**：The harness's cross-clone boundary for the root registry. `mstar-artifacts` states the default policy verbatim: the clone handoff surface is tracked `{HARNESS_DIR}/AGENTS.md`, `{KNOWLEDGE_DIR}/**`, `{SPECS_DIR}/**` and root `CONCEPTS.md` / `STRATEGY.md`, and `status.json` / `workflows/` are explicitly NOT that surface. This repository force-added `status.json`, so one half of a two-document lifecycle is versioned and the other half is not. Consequence observed: the registry row is read by the engine while its `dir` is absent, so the lifecycle it describes cannot be inspected from that checkout at all. Two candidate closers: (a) untrack `status.json` (`git rm --cached .mstar/status.json`) so both halves stay machine-local runtime state, or (b) track the snapshot directory too, so a registration always arrives with its document. Either way the closing condition needs one check that every row in the registry resolves to an existing directory in the checkout that reads it.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-22
- **Revision**：1

### I-000042 [medium] (review-obligation)

**`video_parts.processing_status` carries an unreachable state (`metadata_collected`), so `v_pending_metadata` and the `status` command's `pending:` line report a backlog that can never shrink.**

- **Impact**：`storage/schema.sql`'s `video_parts.processing_status` domain (`discovered` | `metadata_collected` | `gone`) and the view that reads it, `v_pending_metadata` (`schema.sql:156`), surfaced by `status` as `pending:` (`cli.py:1684-1690` via `list_pending_parts`, `storage/database.py:659`); `docs/metadata-storage.md:80` documents that view as 'the `status` command's pending work'. Only `discovered`, and per the knowledge base `gone`, are meaningful in practice, so `pending:` is a constant equal to the part count. This is not a wrong-action bug: `derive-manifest` deliberately reads the other queue (`v_pending_subtitles` through `list_pending_subtitle_parts`) and `cli.py:1209-1211` documents that separation, so no command acts on the misleading number. It is a false operator signal whose fix is a design choice rather than a patch: (a) write `metadata_collected` from a real second pass, (b) redefine `v_pending_metadata` to read the condition it actually means, or (c) drop the state and the view.
- **Acceptance**：defer
- **Owner**：@architect
- **Registered**：2026-09-25
- **Revision**：1

### I-000044 [medium] (review-obligation)

**UNREADABLE-BUT-PRESENT FILE IS COUNTED AS `missing`. `reconcile_audio_inventory` catches OSError from the digest read and increments `missing`, but contract §3.1 defines `missing` as a manifest row that NAMES an audio_path whose FILE IS NOT THERE. A present-but-unreadable file (permissions, I/O error) is therefore reported under a counter whose definition excludes it -- the local-redefinition §3.1 forbids. The PM chose it because the alternatives are worse (no digest means the object cannot be recorded; counting nothing would hide the file entirely), but the choice is unruled. Needs a product ruling: a fifth counter, a stderr warning with no counter, or an explicit §3.1 amendment.**

- **Impact**：src/bili_asr/services/audio_inventory.py — `reconcile_audio_inventory` increments `missing` at :210-212 (a row that names an `audio_path` whose file is absent), while the `except OSError` at :253 covers a present-but-UNREADABLE file and deliberately does NOT increment it (the module says so in its own comment); both are set against the audio-retention contract §3.1's counter definitions.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000046 [medium] (review-obligation)

**Compass AC 6 was recorded as MET while `derive-audio-inventory` did not exist in any commit, and the audio-inventory plan row read `Done` at 0 of 15 Steps. Both were corrected by the PM on 2026-09-28 after the Phase 3 entry checklist caught it, and compass frontmatter was reset completed -> active. This is the same failure mode as R4 on the metadata plan (an external writer recording completion that was not earned) and it is registered so the close-out records HOW the false state was introduced, not only that it was fixed. Note the compensating fact: AC 4 and AC 5 DO hold, with real test coverage, but they were earned by other lifecycles -- so the earlier Done was not wholly false, only unsupported by this plan.**

- **Impact**：documentation and close state only: `{ITERATION_DIR}/iter-2026-09-metadata-audio-layout/delivery-compass.md` frontmatter (completed -> active) + AC 6, and the `derive-audio-inventory` plan row; no product file
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000051 [medium] (review-obligation)

**A fresh L2 re-review of the fix round is OWED. fb09a37 changes src in three files to close nine Important findings; the PM both wrote and mutation-verified it. An arm-length read is still the only thing that catches what the author cannot see -- in the previous round the author found 2 defects and the reviewer found 9. Dispatch a code-reviewer over bda9465..fb09a37; task-2-fix-brief.md names each ruling so the reviewer can judge the implementation against the decision rather than re-deriving intent. STATUS 2026-09-28: the FIRST re-review dispatch PROBED FOR ~42 MINUTES on isolated git-archive copies and then FAILED with no verdict. It was not wasted: its surviving /tmp/revprobe scripts produced TWO further REAL defects, both reproduced by the PM and now fixed -- (a) F8 harder shape: byte-identical files oscillate the store (audio_objects allows one row per sha256, so three identical files repointed it on every run: measured recorded=2 each time with the key bouncing A->B->C->B); fixed by treating a candidate whose CONTENT is already held as `already` (dad656d). (b) F4 honesty: the fb09a37 commit claimed "the summary still prints" on the failure path and it did NOT (the except returned before printing), and its count was the store TOTAL, not what the walk wrote; fixed in 62ed247, with the three unknowable counters marked `?` rather than invented. BOTH are the same failure mode the PM keeps committing: a claim one step ahead of its evidence. A COMPLETED arm-length verdict on the branch is STILL OWED -- dispatch a fresh reviewer over bda9465..62ed247 and tell it to Write the report skeleton first and to budget for the verdict rather than exhausting itself on probing.**

- **Impact**：the fix round's diff bda9465..fb09a37 over src/bili_asr (three files) — the arm's-length verdict; the two defects the failed dispatch did surface are fixed in dad656d and 62ed247
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000053 [medium] (review-obligation)

**Per-video tag fetch is unpaced sequential GETs (~2x page RTTs on full-corpus runs). Needs the MQ3 rate-limit/pacing ruling before any full-corpus collection.**

- **Impact**：the metadata-enrichment plan surface (src/bili_asr/services/metadata_ingest.py, storage/*)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000056 [medium] (review-obligation)

**`page.total` from recArchivesByKeywords is not a row count and must never bound a walk: on mid 23191782 it reports 1739 against 1730 rows served (and keyword `爱情` 13 vs 12), so a `total` below the true count would shrink `ceil(total/ps)` and silently drop whole pages.**

- **Impact**：src/bili_asr/bili_client.py (fetch_pages: the two `total`-derived stops, now removed) with bili_asr/run_ledger.py (the `complete (total N)` display, now `observed_total`). REACHABILITY: fetch_pages has no production caller — `fetch-meta` runs the WBI-signed x/space/wbi/arc/search path (MetadataIngestor + BilibiliApiGateway) and terminates on empty pages only, and the CLI exposes no keyword entry point. The live path records `observed_total` as diagnostics and compares it to nothing. So the shipped fix is hardening for a re-enabled path, not a live repair.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-30
- **Revision**：1

### I-000057 [medium] (review-obligation)

**GatewayShapeError from the tag endpoint fails the whole page+run: a durable upstream shape change at this endpoint becomes a self-inflicted availability wall. Shape-resilience decision owed.**

- **Impact**：the metadata-enrichment plan surface (src/bili_asr/services/metadata_ingest.py, storage/*)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000062 [medium] (review-obligation)

**A chain/ASR-produced artifact publishes `video_title: ""`, because manifest rows carry no video title**

- **Impact**：bilibili-asr-archive/src/bili_asr/archive.py:488 (emission, ruled: emit always, pinned) with the deferred manifest half: services/manifest_derivation.py `row_for_part`, services/transcript_projection.py `projection_row`, storage/schema-transcripts.sql `v_pending_subtitles`
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000066 [medium] (review-obligation)

**`schedule` cannot reach the legacy manifest queue route: it has no `--queue-source` flag, so the 12 schedule/long_live tests whose fixtures hold a caption cannot be pinned the way the other 25 can. The store route classifies such a row `meta_ok` ("go harvest") and the run exits 2.**

- **Impact**：`src/bili_asr/cli/parser.py` (the `--queue-source` flag exists on asr/pilot/download-audio/run but not `schedule`), against `tests/test_scheduler.py` (7) and `tests/test_long_live.py` (5).
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000068 [medium] (review-obligation)

**The store route cannot express "`meta_ok`, go harvest" through `pilot`: `entry_for_item` relabels a harvest-eligible row `needs_audio`, which is in `_PILOT_SKIP_HARVEST`, so the harvest is skipped and the pilot's subtitle / audio-asr branch split collapses.**

- **Impact**：`services/queue_source.py:78` (`entry_for_item`'s status vocabulary) and `cli/pilot.py:369-384` (the store branch merges the audio+transcript queues and then skips `needs_audio`). Tests: the 9 pinned sites in `tests/test_cli_pilot.py` (:117,:175,:293,:312,:362,:390,:447) and `tests/test_mixed_outcome_contract.py` (:519,:565), whose fixtures seed `meta_ok` rows with no caption raw.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000070 [medium] (review-obligation)

**The queue view `v_pending_subtitles` cannot gain a column in place: `CREATE VIEW IF NOT EXISTS` is a silent no-op on an existing archive**

- **Impact**：bilibili-asr-archive/src/bili_asr/storage/schema-transcripts.sql:106-145 and database.py `initialize_schema` (:154-172), which executes only CREATE ... IF NOT EXISTS
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000072 [medium] (review-obligation)

**An external actor committed and merged a fix round into the integration branch mid-round, before review, and only the source half**

- **Impact**：feat/20260926-video-metadata-enrichment (a8670a3, source) and the integration branch merge 8c29c27 (parents 9d530cd a8670a3); 7470ef0 (the D16 test pins) is NOT on the integration branch
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000078 [medium] (review-obligation)

**Gap views probe part_audio_objects/video_part_id and sort by videos.pubdate with no declared indexes — depends on SQLite automatic-index decisions. Land indexes in the follow-on queue-cli-cutover plan.**

- **Impact**：src/bili_asr/storage/{schema-transcripts.sql,database.py,models.py} + tests/test_storage_*.py
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000079 [medium] (review-obligation)

**_PUBDATE_CHUNK=900 chunk loop has no boundary test (no 900/901-row case).**

- **Impact**：src/bili_asr/storage/{schema-transcripts.sql,database.py,models.py} + tests/test_storage_*.py
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000085 [medium] (review-obligation)

**coverage --quality diagnostic gate has no backlog filter: exits 1 on retryable_attempt diagnostics while plain coverage filters them; unreachable divergence today but README overclaims the guarantee.**

- **Impact**：src/bili_asr/{integrity.py,quality.py,cli.py} + tests/test_{integrity,cli_exit_contract,quality}*.py + README
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000089 [medium] (review-obligation)

**README documents retryable_attempt as never exit-moving; the guarantee only holds on the plain coverage path (same root as D-R1).**

- **Impact**：src/bili_asr/{integrity.py,quality.py,cli.py} + tests/test_{integrity,cli_exit_contract,quality}*.py + README
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000095 [medium] (review-obligation)

**NO ARM'S-LENGTH L2 VERDICT on the shape A diff (d42f903..40eea78, merged as PR #26). A review seat was dispatched and produced no report. The delivered verification -- publish crash windows, symlink/traversal, the collision-probe fix, the end-to-end CLI run -- is author-run. The collision-probe defect that author probing found is the evidence an independent read adds value, so a fresh read-only seat over the merged diff is owed.**

- **Impact**：the merged shape A diff d42f903..40eea78 (PR #26, d743043) — the arm's-length L2 review, not product code
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000098 [medium] (review-obligation)

**SIZE: the character record costs 8.55x, not the planned 2.8x, and both levers touch serialization shared with published artifacts**

- **Impact**：the raw sidecar's serialization — archive.py:631 (json.dumps(..., indent=2)) and the timestamp precision carried from asr.py:1183-1184 (float(unit[...]) + offset, where offset is boundary_samples/16000.0)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000099 [medium] (review-obligation)

**TEST INFRA: conftest's tmp_root raises FileExistsError on PID reuse, making any lane's verification randomly red**

- **Impact**：tests/conftest.py:125-138 (the tmp_root fixture) — it names dirs manifest-test-{pid}-{counter} under a shared <repo>/.test-tmp/
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000100 [medium] (review-obligation)

**SILENT PASS: the 'accept any parseable sidecar' shape likely exists in proofread's sibling readers of bundle.raw.json**

- **Impact**：readers of bundle.raw.json other than proofread.read_asr_route_ms — the same defect class as C-1, which produced an all-agree-1.000 table that reported success
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000102 [medium] (review-obligation)

**Task 4 (真机重跑与验证) was never delivered: the plan's code work (Tasks 1-3) is complete and merged, but the ON-HARDWARE verification — re-running the four artefacts on GPU and hand-inspecting at least 5 proofread blocks — has no report, no evidence, and no run record.**

- **Impact**：Task 4 of plan 20261001-cue-timeline-and-proofread (budget 3): transfer the new build to the target host, create a NEW artefact root (not route1/route2, per D-2), re-run the four GPU transcripts, and record the before/after table, GPU wall time, the `characters` field's measured size growth, and a side-by-side proofread table with >=5 blocks hand-inspected.
- **Acceptance**：accept
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000103 [medium] (review-obligation)

**`coverage --reference` refuses any pair whose flattened transcript exceeds `_MAX_COMPARE_CHARS = 20 000` (`quality.py:104`), so the product's own cross-system telemetry — the `ReferenceAgreement` ratio and the `reference_disagreement` flag — is unavailable for exactly the long items a reference check matters for: 2 of the 6 measured rows exit 1 with `coverage: reference too large to compare` and no alternative surface.**

- **Impact**：The reference-comparison surface's bound and what it costs. The bound itself is deliberate (the docstring states `_MAX_BYTES` does not bound the *work* of comparing, so the flattened pair is bounded too), and the refusal is honest — but it is all-or-nothing: an item longer than ~75 minutes of speech loses the metric entirely rather than getting a sampled or windowed one, and the exit code shares the command with real failures. Two closers: a bounded comparison that still answers (windowed/chunked with the window stated in the payload), or the published limit plus a surface that says which rows were refused and why, so an operator can tell 'too long' from 'broken'. Closing condition: a long row (flattened > 20 000 chars) yields a determinate comparison result or a named, documented refusal the caller can branch on.
- **Acceptance**：defer
- **Owner**：@architect
- **Registered**：2026-09-22
- **Revision**：1

### I-000104 [medium] (review-obligation)

**The two branches write different manifest row shapes: an **ASR** `archived` row carries `audio_path` and `page_label` but **no** `source` and **no** `language`, while a **caption** `archived` row carries `source` and `language` and neither of those — so on the audio path `search --source` can never match, `export` has no source field to report, and `verify` reports `authoritative: false`.**

- **Impact**：One emitter, three readers. The ASR stage records its provenance in the artifact sidecars and in the store's absence (see this bucket's R3) but not on the manifest row, and the row shapes have drifted apart per branch. Two closers: one row shape carrying the branch's provenance (`source`, `language`, plus the per-branch extras) so the readers can distinguish rather than guess, or a recorded decision that ASR rows are identified some other way — with `search`/`export`/`verify` updated to read it. Closing condition: `search --source` and `export` can name the ASR rows and `verify` can be authoritative on an audio-only root, pinned by a case.
- **Acceptance**：defer
- **Owner**：@fullstack-dev
- **Registered**：2026-09-22
- **Revision**：1

### I-000105 [medium] (review-obligation)

****ASR work never reaches the store**: after six successful GPU transcriptions the root's `archive.db` still holds `transcripts = 0`, `transcript_segments = 0`, `asr_models = 0`, `audio_objects = 0`, `acquisition_attempts = 0` and `part_audio_objects = 0`, so the store's pending view never drains from ASR work and the ASR products' only durable record is the file tree plus the append-only manifest.**

- **Impact**：A deliberate scoping measured against its consequences, not a claim that the code is wrong. `{KNOWLEDGE_DIR}/architecture-patterns/normalized-transcript-storage.md` states it: the store's shape 'is meant to carry local ASR rows later, so the caption-only parts of it are scoped deliberately', and `schema-transcripts.sql` reserves `source_kind = 'asr-local'` while leaving its version-key widening ('per model/run, that decision belongs to the ASR owner') open. What this run adds is the measured cost of leaving it open: the queue derived from the store stays 'no transcript' for parts the ASR branch has already archived (only the manifest row prevents re-work), the product tables cannot answer for ASR work, and this bucket's R2 (no `source`/`language` on the row) and the readers' blindness follow from it. Two closers: wire `asr-local` rows (model identity, uniqueness widening, attempt sidecar) so both branches land in one store; or record the decision that the ASR branch is file/manifest-only by design and make `status`/`search`/`export` say so on such a root. Closing condition: one of the two is recorded and a case pins the ASR branch's product durability path.
- **Acceptance**：defer
- **Owner**：@architect
- **Registered**：2026-09-22
- **Revision**：1

### I-000112 [medium] (review-obligation)

**The ASR chain has no bridge from archive.db: fetch-meta collects real metadata into SQLite, but asr / pilot / download-audio / run / schedule / campaign read manifest/manifest.jsonl only, and no command derives the manifest from the database (nor the transcripts back into SRT/TXT/MD). A deliberately published boundary (README + docs/metadata-storage.md Boundary) rather than a defect, so every corpus run needs a hand-built manifest.**

- **Impact**：bilibili-asr-archive/src/bili_asr/cli.py (the two command families never share a store) with src/bili_asr/manifest.py and the storage layer; the SQLite side holds exactly ONE work queue and it is the SUBTITLE backlog: the view v_pending_subtitles, whose predicate is processing_status <> 'gone' AND NOT EXISTS (any transcript row for the part) — source-kind-agnostic, and NOT keyed on any acquisition_attempts outcome; the attempt CTE in that view only RANKS kind='subtitle' attempts to expose attempted / last_attempt_at. There is no audio or ASR queue, no per-part audio state, and video_parts.processing_status cannot express one (enum: discovered / metadata_collected / gone). The bridge used by this run is scaffolding on the target host (/root/e2e-asr/tools/seed_season.py, unsupported, not in the repository).
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-17
- **Revision**：1

### I-000118 [medium] (review-obligation)

**The README-published GPU self-check fails in a default shell: bare `bili-asr check-asr-env` exits 1 (`dxg-detection FAIL`, `device-probe FAIL torch.cuda.is_available() == False`) while the same command prefixed with `HSA_ENABLE_DXG_DETECTION=1` exits 0 and names the RX 7800 XT / gfx1101 — the variable the recipe's own step 8 requires be persisted is absent from the host's shell profile.**

- **Impact**：Host configuration against the product's gate contract. The check itself is not wrong: it fails closed when the runtime it needs is not enabled, and its refusal already names the variable. The gap is that the enablement step the project's own docs require (`docs/wsl-rocm-gpu.md` step 8) is not persisted, so the published self-check answers `not verified` from every plain shell — including the shells an ASR run is launched from, where the same unset variable is what the device probe reports. Two closers: the variable is persisted in the host's profile (or set by the documented service/unit that launches ASR work) and a bare `check-asr-env` exits 0 from a fresh login shell; or the docs stop claiming step 8 is required and the operator recipe names the variable as the step. Closing condition: one of the two, verified by a bare invocation on this host.
- **Acceptance**：defer
- **Owner**：@ops-engineer
- **Registered**：2026-09-22
- **Revision**：1

### I-000122 [medium] (review-obligation)

**The artifact-root configuration's operational hardening is missing: the cap/peak measurement re-based onto the artifact root **walks the whole `audio/` tree once or twice per row** (a network round trip on the intended WebDAV mount), the same measurement **fails open** (an unreadable/absent mount yields 0 bytes, silently disabling the cumulative guard and printing the 0 as evidence), and the boundary's validation **opens** the root but never probes a write or a directory `fsync`, so a mount that opens and then rejects directory fsync passes validation and fails every row with a raw error instead of the four-line refusal.**

- **Impact**：`audio_budget.py` (unchanged by the plan, re-based by its callers), the coordinator's `_note_audio_peak`/`_stage_download`, the CLI's per-row cap check, and `artifact_root.py`'s boundary validation. Not a defect of the delivered split: state still stays local and the refusal ordering holds. **Close condition must enumerate all four items** (the per-row walk cost, the fail-open measurement, the write+directory-fsync probe, and qc3's Suggestion S1 - a fixture for each), **plus** qualifying the unqualified `fail-closed` claims - `docs/artifact-root.md:141` (done in fix wave 2) **and the two siblings the wave did not reach, `docs/audio-retention-policy.md:39` and `:179`** (qc3's re-review finding), **plus** qc3's S2 (probe budget multiplied by the base count in per-row loops) and S3 (one `schedule --allow-long-live` run measures usage twice by different recipes, so the printed plan can disagree with the batch's own skip), which the QC re-review found unregistered.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-19
- **Revision**：1

### I-000123 [medium] (review-obligation)

**The path-to-base pairing is re-implemented in five modules: `ArtifactRoots` centralises root **resolution** (one `roots_for` call in `main()`), but the rule "which base holds this recorded value" exists as four audio pairings with different predicates plus **two identically named bundle helpers with different bodies** - **five** pairing sites after fix wave 2 added `cli._audio_base_for_path` — the structural reason qc1's Critical (pilot re-confining a legacy row's audio against the write base) was reachable.**

- **Impact**：`artifact_root.py`'s value object and every reader/writer call site that pairs a recorded value with a base. **A fourth specific (disclosed by the fix wave and CORRECTED by both re-review seats, 2026-09-19):** the holding-base rule in `_audio_base_holding`/`_declared_audio`/`_audio_base_for_path` picks by **existence**, while the two `_existing_audio` helpers require a usable size (`st_size > 0`). **The consequence is NOT a failed row** - both seats probed it: a 0-byte stub at the configured root is skipped by the producer, the valid legacy copy is returned, and on the recorded branch the row simply falls through to the (now corrected) download branch. What the divergence actually costs today is **one extra download-stage fast-path call**. The rule still matters because a future existence-only call site could reintroduce the difference - so the shared resolver should fold **validity** (existence *and* a usable size) into the base choice. *(The earlier text in this row said the stub makes the row fail closed; that was the PM's inference, not a measurement, and two seats disproved it - the same claim-wider-than-the-code class this iteration keeps catching.)* **Also: the enumeration is stale by one** - `cli._audio_base_for_path` (added by fix wave 2) is a **fifth** pairing site, and qc3's S4 (the download branch validates the same absolute path twice and re-derives its relative form where the coordinator's sibling returns the pair in one pass, with a mount flap between the two probes surfacing as the same `invalid audio path` refusal) sits inside this row's scope and needs no separate entry.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-19
- **Revision**：1

### I-000125 [medium] (review-obligation)

**Two-pass hotword re-seed orchestration duplicated verbatim between cli.py _cmd_asr and coordinator.py; drift hazard — extract a shared helper.**

- **Impact**：src/bili_asr/cli.py `_cmd_asr` (:2721, the two-pass call at :2863) duplicated verbatim in src/bili_asr/coordinator.py (:599); the shared seam is asr.py `rebuild_hotwords_from_first_pass` (:1180)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000126 [medium] (review-obligation)

**Store-sourced asr/pilot queues re-decode parts whose transcripts were archived by manifest-era runs before the cutover (v_missing_transcript keys on store evidence only). Cutover migration note owed.**

- **Impact**：src/bili_asr/services/queue_source.py (`select_audio_queue`/`select_transcript_queue`, :109/:115) against src/bili_asr/storage/schema-transcripts.sql `v_missing_transcript` (:228)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000127 [medium] (review-obligation)

**search_blocks issues one MATCH snippet query per hit and eagerly scans videos titles, unbounded by limit; latency scales with corpus size.**

- **Impact**：src/bili_asr/search_index.py `search_blocks` (:1447) — the per-hit snippet MATCH and the eager `videos` title scan
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000128 [medium] (review-obligation)

**Store runs in rollback-journal mode (no WAL pragma); a crash mid index-build leaves a torn prefix the transcript-id stamp cannot detect. Committed-batch watermark owed.**

- **Impact**：src/bili_asr/storage/database.py (the sqlite connect at :210 sets no `journal_mode`) with the index-build/stamp path in src/bili_asr/search_index.py
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000135 [medium] (review-obligation)

****`uv.lock` is stale through several engine changes, so the `uv sync` install path a reader follows installs a closure the product no longer uses.** Its root `asr` extra still lists `funasr` — dropped when the engine moved to Qwen3-ASR — and carries no `accelerate`, while the README documents `uv sync` as supported and `pyproject.toml` declares transformers/accelerate/soundfile/soxr. The pip path is unaffected because it reads `pyproject.toml` directly.**

- **Impact**：`bilibili-asr-archive/uv.lock`, and therefore every install that follows the README's `uv sync` path rather than `pip install -e ".[asr]"`. The pip path was never affected because it reads `pyproject.toml` directly.
- **Acceptance**：accept
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000138 [medium] (bug)

**ManifestStore.compact deletes journal when snapshot absent, losing the only durable copy of journaled rows**

- **Impact**：Journal data loss on compaction when manifest.jsonl absent/empty
- **Acceptance**：compact() must not unlink the journal when current is empty (mirror migrate guard) or write snapshot unconditionally when journal non-empty
- **Owner**：project-manager
- **Registered**：2026-10-01T20:11:29.604Z
- **Revision**：1

### I-000139 [medium] (bug)

**search_index.is_stale uses snapshot mtime only, journal-blind to same-count manifest transitions**

- **Impact**：FTS index can serve stale rows when a same-count manifest change leaves snapshot mtime unchanged
- **Acceptance**：is_stale incorporates journal mtime/content so a journaled same-count transition invalidates the index
- **Owner**：project-manager
- **Registered**：2026-10-01T20:11:30.151Z
- **Revision**：1

### I-000140 [medium] (risk)

**ManifestStore.upsert caches _entries across calls with no cross-process invalidation; interleaved appends from another process are overwritten on save/compact**

- **Impact**：Concurrent/parallel archive invocations sharing one root can lose rows (stale-SSOT write)
- **Acceptance**：upsert revalidates (replays on journal/snapshot change) or versions _entries and refuses cross-process staleness
- **Owner**：project-manager
- **Registered**：2026-10-01T20:11:30.666Z
- **Revision**：1

### I-000141 [medium] (bug)

**Metadata gateway _pace uses time.sleep inside async getters, blocking the event loop**

- **Impact**：Event loop frozen 0.8-1.6s per upstream metadata call (~72-144s per 30-video page), stalling SQLite writes + progress
- **Acceptance**：_pace awaits asyncio.sleep (or runs time.sleep via asyncio.to_thread) while keeping the _sleeper/_jitter injection seam
- **Owner**：project-manager
- **Registered**：2026-10-01T20:11:31.266Z
- **Revision**：1

### I-000145 [medium] (bug)

**Pre-existing test drift: 18 failures in test_scheduler/test_coordinator/test_metadata_cli (recovery contract + rerun manifest + processed_work_ids)**

- **Impact**：18 pre-existing test failures on main mask real regressions in the coordinator/scheduler/metadata lanes; sorted FAILED set byte-identical base vs head (not introduced by this iteration)
- **Acceptance**：A dedicated plan fixes the recovery-contract drift (integrity.py vs test expectations), the rerun manifest path, and the processed_work_ids/subtitle_done fixture gap so these suites go green
- **Owner**：project-manager
- **Registered**：2026-10-01T21:05:54.255Z
- **Revision**：1

### I-000156 [medium] (bug)

**Store route cannot express a captioned-but-unarchived row: 6 scheduler/long-live fixtures assert archive-through-store-route (plan store-route-expressiveness STOP)**

- **Impact**：behaviour gap / red tests masking regressions
- **Acceptance**：A contract-sanctioned selection surface for captioned-but-unarchived parts lands and the 6 fixtures assert it
- **Owner**：project-manager
- **Registered**：2026-10-02T07:00:55.571Z
- **Revision**：1

### I-000167 [medium] (bug)

**AUDIT-2026-10-02R2: the manifest journal never compacts on any in-repo path, so every process and projection re-parses a monotonically growing ledger and the deterministic snapshot is never refreshed**

- **Impact**：Compaction requires BOTH a per-instance counter (>=256 appends) AND journal_bytes >= 2x snapshot_bytes, and no src caller invokes save()/compact(). Normal invocations append far fewer than 256 rows per process, so the counter resets before the byte clause can hold and the journal is only ever folded by a method nothing calls. Read cost per fresh process and per projection (load, replay_journal_records, SearchIndex.is_stale) is unbounded in the number of transitions ever recorded rather than in corpus size.
- **Acceptance**：Compaction is reachable from a normal path (bytes-based trigger and/or an exposed maintenance command); a test proves the journal shrinks after N cross-process appends and that the snapshot-absent case keeps the journal intact (I-000138 boundary preserved).
- **Registered**：2026-10-02T14:52:51.503Z
- **Revision**：1

### I-000168 [medium] (bug)

**AUDIT-2026-10-02R2: opt_in_gate returns but never skips, so the 'central gate' plan 008 landed is advisory and a new opt-in test without its own pytest.skip runs against the live network / a 100s scale fixture**

- **Impact**：tests/conftest.py:209-225 resolves the marker->env mapping and returns (env_var, marker) without calling pytest.skip; all five consumers still hand-roll their own skip, and nothing asserts the fixture skips. Plan 008's declared outcome (one shared conftest fixture that skips centrally) is not what the tree does. A future opt-in test that takes the fixture and omits the manual skip runs unconditionally in the default suite.
- **Acceptance**：opt_in_gate performs the skip itself (reason supplied by the caller) and a rehearsal test proves an unopted-in marked test is skipped by the fixture alone.
- **Registered**：2026-10-02T14:53:07.343Z
- **Revision**：1

### I-000169 [medium] (improvement)

**AUDIT-2026-10-02R2: manifest.journal.jsonl is a new durable artifact the operator contract never names, and the README still publishes the pre-journal append-cost model and the pre-write-back store story**

- **Impact**：The delta made the ledger a snapshot + append journal, but README:1000 still calls manifest.jsonl 'the single source of truth' and the archive-root inventory (README:566-570) omits the journal, so an operator who copies/diffs the snapshot reads a stale projection between compactions. README:1309-1312 still states the O(N^2) append cost that plan 003 replaced, and docs/metadata-storage.md:72-77 still says audio_objects/part_audio_objects/asr_models are written by no command although R14 wired all three.
- **Acceptance**：The README names the journal beside the snapshot as the ledger pair, the append-cost paragraph describes the journal ledger, and docs/metadata-storage.md reflects the landed write-back; the affected residual rows (I-000028 premise, I-000105 premise) are re-scoped in the same pass.
- **Registered**：2026-10-02T14:53:19.207Z
- **Revision**：1

### I-000170 [medium] (bug)

**AUDIT-2026-10-02R2: ManifestStore.save() unlinks the journal before rewriting the snapshot while its two siblings do the reverse; the delta's PERF-01 makes this ordering window live**

- **Impact**：save() replays, unlinks the journal, then returns early when current is empty or rewrites the snapshot. compact() and migrate_legacy_rows() write first and unlink after. A crash or ENOSPC between the unlink and the snapshot replace loses every row that existed only in the journal; combined with the journal-never-compacts finding, the journal is where new rows live, so the window is wider than it looks.
- **Acceptance**：save() matches its siblings (snapshot write first, journal unlink only after success) and leaves both artifacts untouched when current is empty; a test proves a failure between write and unlink leaves the journal recoverable.
- **Registered**：2026-10-02T14:53:30.566Z
- **Revision**：1

### I-000171 [medium] (bug)

**AUDIT-2026-10-02R2: write-back page_index defaults to 0, so a legacy bare-bvid row's transcript can be stamped onto p0's video_part_id**

- **Impact**：Four call sites resolve page_index as int(entry.get("page_index") or 0) and the resolver looks the part up by (bvid, page_index). A legacy/unresolved row archives correctly under its bare-bvid stem but its write-back names p0, so the true part stays in v_missing_transcript and p0's row gains a transcript it did not produce. Population on a live root not measured.
- **Acceptance**：Each write-back derives the page identity from the row's work_id (or skips when the row has no resolvable page), and a test proves a bare-bvid row does not stamp p0.
- **Registered**：2026-10-02T14:53:49.557Z
- **Revision**：1

### I-000172 [medium] (improvement)

**AUDIT-2026-10-02R2: SearchIndex.is_stale() repays the full ledger replay plus a per-row filesystem probe on every search (auto_build default)**

- **Impact**：Every `search` (auto_build default, cli/search.py:151) loads and validates the whole snapshot+journal and then runs os.path.isfile over up to 5 relative paths x every read base for each pathless completed row; on the documented WebDAV artifact root those are network round trips per row per query. Cost scales with corpus size per query, not per rebuild.
- **Acceptance**：The freshness check answers 'indexed' from the index's own stamped keys and only probes filesystem rows it cannot know; a test proves search does not stat per-row on a covered corpus while a genuine new row still triggers a rebuild.
- **Registered**：2026-10-02T14:53:50.128Z
- **Revision**：1

### I-000174 [medium] (review-obligation)

**AUDIT-2026-10-02R2: installed console-script lane never opens a database, so packaged schema resources and the dependency closure are unverified in the shipped artifact**

- **Impact**：tests/test_cli_help.py's isolated-install lane calls run_installed four times, only for --help and a status that fails before any DB open; database.py loads schemas via resources.files(__package__) with package-data declared in pyproject. A packaging regression dropping schema.sql/schema-transcripts.sql leaves every installed-lane test green while the shipped bili-asr is unusable.
- **Acceptance**：One installed-lane invocation opens (or materializes) a database through the console script and asserts a schema-derived exit, pinning package-data and the declared dependency closure.
- **Registered**：2026-10-02T14:54:03.769Z
- **Revision**：1

### I-000175 [medium] (improvement)

**AUDIT-2026-10-02R2: verify_baseline excludes test_cli_help.py wholesale, dropping ~44 in-process CLI contract tests from the one baseline lane; the file it references (test_installed_cli.py) does not exist**

- **Impact**：scripts/verify_baseline.py's staged tree ignore-set names test_cli_help.py, which holds 49 test definitions of which only 5 use the isolated_cli fixture; the rest are in-process main()/capsys contract tests (the coverage --reference family). The baseline lane therefore never runs a whole subsystem's CLI surface, and the name the ignore-set already references (test_installed_cli.py) resolves to nothing.
- **Acceptance**：The five installer tests move to tests/test_installed_cli.py (or the in-process family moves out of the excluded file) so the baseline lane covers the contract family; the dangling reference resolves.
- **Registered**：2026-10-02T14:54:20.434Z
- **Revision**：1

### I-000176 [medium] (review-obligation)

**AUDIT-2026-10-02R2: the R14 store write-back has no end-to-end witness — only direct record_local_transcript unit calls**

- **Impact**：The write-back fires only when the store route is active and ensure_asr_run returned an id; tests exercise the service function directly and the chain's ASR arm asserts ledger/attempts only. A regression in the wiring or in the source guard is invisible to every CLI and chain test, while v_missing_transcript keeps listing the part and reruns re-pay the GPU.
- **Acceptance**：One store-route ASR row asserts the transcripts join count for its part, plus one case where ensure_asr_run fails to prove the archive still succeeds without a row.
- **Registered**：2026-10-02T14:54:20.997Z
- **Revision**：1

### I-000177 [medium] (improvement)

**AUDIT-2026-10-02R2: no runnable one-command verification — verify_baseline requires a hand-built offline wheel fixture and the checked-in evidence is a 0-command prerequisite failure**

- **Impact**：There is no command an operator can run on a fresh checkout that answers 'is this tree green': verify_baseline raises PrerequisiteError without a per-host wheel corpus, and verification-results/baseline.json records status prerequisite_failed with 0 commands. Verification stays per-worktree and ad hoc — the condition under which I-000145's pre-existing failures and I-000034's deterministic red survived to this audit. No-CI itself is by-design; the missing local substitute is the cost.
- **Acceptance**：A documented fast lane (e.g. the package-root pytest invocation with the worktree-correct PYTHONPATH) serves as the green/red signal and is recorded in verification-results/README.md, with the offline wheel baseline retained as the release-grade lane.
- **Registered**：2026-10-02T14:54:39.519Z
- **Revision**：1

### I-000178 [medium] (decision)

**AUDIT-2026-10-02R2: decide the parked editorial/reading-edition track — its ~3400 lines are on no main commit and no branch, and both unstarted plan files survive only inside a tracked deletion tarball**

- **Impact**：HANDOFF §1-§3 record the iter-2026-09-transcript-editorial-stages lifecycle as parked with gates open; the align-transcripts / verify-proofread code is reachable only via git fetch origin refs/pull/17/head (refs retired 2026-09-30), and the two un-started plan files exist only as blobs inside docs/archive/deletion-records-20260925/harness-editorial-stages-deleted-20260925.tar.gz. Producing reading editions is the product's evident next value step; without a decision the track is neither resumable-by-a-reader nor formally abandoned.
- **Acceptance**：A recorded decision — rescue (extract the plan files and pin the code ref into the repo), re-scope, or abandon with the recovery path documented — plus the HANDOFF/iteration-index rows updated to match.
- **Registered**：2026-10-02T14:54:40.070Z
- **Revision**：1

### I-000181 [medium] (improvement)

**AUDIT-2026-10-02R2: the README still says the ASR/pilot chain is driven from manifest/manifest.jsonl although the R14 write-back and --queue-source store route have landed on main**

- **Impact**：README:490-492 tells the operator the ASR/pilot chain (download-audio, asr, pilot, run, schedule, campaign) is 'still driven from manifest/manifest.jsonl', while --queue-source store and the transcript write-back are landed (11374d1, aee6f2e both ancestors of main) and writers live at queue_source.py:300,329. An operator following the README on a fresh root builds a manifest by hand for a path that no longer needs it; the same drift makes a measured full-corpus run look premature.
- **Acceptance**：README describes the store route as the default chain input with the manifest route as the explicit fallback, and the affected legacy rows are re-scoped; the pre-landing rows in roadmap/milestone records are corrected in the same pass.
- **Registered**：2026-10-02T14:55:16.332Z
- **Revision**：1

### I-000182 [medium] (bug)

**E2E-2026-10-03: a kind=asr acquisition run is never finished — every ASR run stays outcome=running with finished_at NULL**

- **Impact**：Any consumer that asks whether an ASR run has completed (run ledger display, resume logic, an integrity/coverage reader keyed on acquisition_runs.outcome) gets the wrong answer permanently. In the E2E run of 2026-10-03 the successful single-part ASR invocation left run_id=asr-1790983612 at outcome=running, finished_at=NULL, while the two subtitle-run controls were both closed to outcome=complete — so the asymmetry is the ASR path specifically.
- **Acceptance**：After an asr invocation returns, its kind=asr acquisition_runs row carries a terminal outcome and a finished_at value; a regression test pins the close-out; the subtitle path's existing finish_acquisition_run call sites stay unchanged.
- **Registered**：2026-10-02T23:36:06.682Z
- **Revision**：1

### I-000186 [medium] (improvement)

**The issue-close channel is unreachable in practice: every privileged issue mutation needs an engine-issued session envelope bound to a live workflow snapshot, and no workflow in this repo has ever recorded that binding**

- **Impact**：A completed verification run can prove an issue is stale — with passing witness tests and a hardware reproduction — and still cannot record that conclusion in the store. Measured: of 32 resolved issues, all 32 came from the legacy import and 0 were closed through a live channel; the store holds 0 issue->plan provenance links, so the plan-scoped route (which by contract closes only its own findings) cannot be used by any plan. The consequence is a permanent drift: the open count never reflects verified reality, and the next reader re-litigates issues that already have dispositive evidence.
- **Acceptance**：Either the engine provides a reachable close route for an engine-issued session on a live workflow (binding recorded by the sanctioned prepare/register path), or the contract documents the operator-side/manual close as the intended route for out-of-plan findings; a test pins whichever answer is chosen. Until then, a verified-stale issue is reportable but not closable.
- **Registered**：2026-10-03T00:09:36.869Z
- **Revision**：1

### I-000189 [medium] (bug)

**proofread-merge drops a block whose side-by-side row is missing, exits 0, and still counts it in the accounting — a marked-up 定稿 can lose text without any signal**

- **Impact**：An operator who marks a 定稿 and accidentally loses a block's `| a | b | c |` row gets a merged transcript silently missing that block, exit 0, and a corrections accounting that counts the block as decided. The published `.proofread` artifact is then wrong in a way nothing reports, in a pipeline whose whole purpose is adjudicated accuracy.
- **Acceptance**：A non-custom block with no row under its heading is refused on the merge path (exit 1 naming the block), or the accounting distinguishes blocks contributing no text; a test pins the missing-row case.
- **Registered**：2026-10-03T00:42:32.988Z
- **Revision**：1

### I-000193 [medium] (bug)

**A terminal caption row whose best-effort write-back failed can never acquire its transcripts row, and the failure is no longer durably attributed**

- **Impact**：After plan caption-writeback-guard, a caption row that published and was marked `archived` whose store write-back then failed sits in TERMINAL_STATUSES with no `transcripts` row. `record_caption_transcript` has exactly one caller chain (coordinator.py:866 -> :755) and `process_row` early-returns for terminal rows (:1062-1065), so no product path (run / schedule / campaign / harvest-subs / recover) re-drives that part's write-back: it stays in `v_missing_subtitle` (and `v_missing_transcript` where audio evidence exists) permanently. The failed write also leaves no durable per-row record — the attempt ledger says `archive: ok, error_code: null`, so `run --scope failed` and the coverage/integrity attempt readers (coverage_report.py:437-451, search_index.py:405-420, cli/run.py:56-62) cannot surface it; only the transient stderr line and the run-ledger `exit_code: 1` survive. This is a net-positive trade (pre-fix the same input left a non-terminal row that re-failed forever, i.e. never converged) — but the residual must be tracked so 'invariant restored' is not later read as 'the part left the gap view'.
- **Acceptance**：Two properties hold: (a) a part whose best-effort write-back failed is identifiable from durable state alone (an attempt-ledger or store-level signal a reader can query — not a transient stderr line), and (b) such a part is re-drivable, or its unrepairability is recorded as a tracked decision. Verified when: an injected store failure on the caption path leaves a durable, queryable record naming the part and the failure, and either a documented repair path exists or the gap-view consequence is accepted in writing with its owner.
- **Registered**：2026-10-03T04:34:15.234Z
- **Revision**：1

### I-000194 [medium] (bug)

**The same defect class survives in cli/asr.py: the ASR write-back runs before the row is marked archived and inside the archive try, so one store failure reports a published bundle as `archive failed`**

- **Impact**：`bili-asr asr` publishes the bundle at cli/asr.py:268, verifies completeness at :273, then performs the store write-back at :290-299, and only afterwards sets `updated["status"] = "archived"` and upserts (:300-303) — the whole span sits inside the per-row handler's try opened at :224, whose `except Exception` (:312-321) prints `archive failed (<code>)` and increments `failed`. So a store-side failure after a successful publication reports the row as failed and never marks it archived: the same class as I-000165, on the ASR route rather than the caption route. Plan caption-writeback-guard fixed only the coordinator's caption stage, and its Stop-Out-of-scope list did not cover this file, so the class is now closed in coordinator.py and open here. Reachability of a raising cue shape on this route was not independently reproduced by the finding seat.
- **Acceptance**：The ASR route satisfies the same invariant plan caption-writeback-guard established: once the bundle is published and its completeness verified, the row is recorded `archived` regardless of the store write-back's outcome, and a write-back failure cannot turn a published row into `archive failed`. Verified when: a test drives `bili-asr asr` (or the equivalent handler body) with an injected store failure after publication and asserts the row reaches `archived` and the CLI does not report that row as archive-failed.
- **Registered**：2026-10-03T04:35:30.037Z
- **Revision**：1

### I-000206 [medium] (bug)

**Cross-plan integration: the new file-based fold trigger compacts the journal mid-run, so a sibling plan's regression test that read the journal file found it already folded**

- **Impact**：Plan journal-compaction-lifecycle's Task 1 replaced the per-instance 256-append counter with an on-disk byte rule (`max(512, 2 x snapshot)`), which folds far earlier than the old conjunction whenever the snapshot is small or absent. Plan caption-writeback-guard's regression test (`tests/test_coordinator.py::test_run_batch_subtitle_archive_records_published_bundle_when_writeback_fails`) reads the run's manifest write out of `manifest/manifest.journal.jsonl`, on the reasoning recorded in its own comment that folding 'belongs to the store's own compaction path, whose trigger this test deliberately does not restate -- another plan in this iteration reworks it'. That premise held when the test was written and broke when the sibling landed: measured trace of the real run gave `FOLD_EVAL S=0 J=606` followed by `REMOVE`, i.e. the journal is folded and unlinked mid-run, and the test then failed with `FileNotFoundError` on the journal path. The rows themselves were never at risk -- the fold publishes them into the snapshot first, and the snapshot contains the run's `archived` row -- so this is a **test-observability** break, not a data defect. Isolated by bisection to `f6e9c5e` (Task 1+2), independent of the Task 4 base change; 2/2 runs failed at `f6e9c5e` and 2/2 passed at the pre-plan state `4357617`.
- **Acceptance**：The cross-plan test reads the run's manifest write from whichever artifact actually holds it, and still fails when the behaviour it pins is reverted. Verified when: the test passes on the merged iteration head; it still fails with `caption-writeback-guard`'s fix reverted (the property it exists to pin), which was confirmed by reverting `coordinator.py` to `1e756df` in a scratch worktree and observing the failure; and each branch asserts only what its file can witness (journal: the `subtitle_done` -> `archived` transition as a sequence; snapshot: the same row as final state, since the snapshot keeps last-wins per work id).
- **Registered**：2026-10-03T14:42:18.714Z
- **Revision**：1

### I-000209 [medium] (improvement)

**The repository has no CI: nothing runs the test suite automatically, and iteration/PR gates that assume "required CI is green" resolve vacuously**

- **Impact**：Verified 2026-10-03: the repo has no `.github/` directory at all, no `.gitlab-ci.yml`, `.circleci/config.yml`, `Jenkinsfile`, `.travis.yml`, `azure-pipelines.yml`, `.woodpecker.yml`, `.drone.yml`, `.buildkite/pipeline.yml` or `bitbucket-pipelines.yml`, no `.pre-commit-config.yaml`, no husky hooks, and no active git hooks. `gh pr checks <n>` reports "no checks reported" for every PR. The consequence is not just missing automation — it is that the Morning Star iteration gates silently lose a leg. Phase 5 §5.2's checklist item "All required CI checks green on latest head" and the phase-4/5 route map's "CI 全绿" predicate are **vacuously satisfied** rather than verified, so a PR reaches "merge-ready" on local evidence alone. That is how this iteration's own PR #35 was merged: merge-ready rested on per-plan tri-review QC, per-plan QA gates, and a cross-plan failure-set diff against the base — real evidence, but **all of it authored and run in the same session that wrote the code**, with no independent runner. The pytest configuration shows CI was intended: `pyproject.toml:78-80` registers the `live_smoke`/`scale`/`slow` markers explicitly so the gated tests are "selectable ... and CI-gateable", and audit plan 008's motivation records that 35 live/smoke/scale tests are "invisible to collection metadata (no `-m`, no CI gate)" — the markers landed, the gate they were for did not. A prior iteration's compass even lists "required CI is green" as a merge-readiness criterion, so the expectation is recorded in the harness while the thing itself is absent.
- **Acceptance**：Either the repository has a CI workflow that actually runs the suite on PRs (at minimum the default, non-opt-in test selection, plus the harness validator as a cheap gate), so a PR's green state is machine-verified rather than asserted; or the harness/pipeline documents that this repo is deliberately local-verification-only, so Phase 5's "required CI" item is understood as not-applicable instead of silently passing. Verified when: a PR shows a real check run whose failure would block merge, or the delivery-compass/pipeline text states the local-only decision and the merge-readiness criteria no longer claim a CI gate.
- **Registered**：2026-10-03T16:02:20.442Z
- **Revision**：1

### I-000210 [medium] (bug)

**Two credential-absent harvest runs satisfy the empty-inventory corroboration rule, so an anonymous pair can confirm caption exhaustion without any credential having seen the inventory**

- **Impact**：v_missing_audio now requires two independent empty observations before an indefinite negative admits a part, where independent means a distinct run_id. The rationale for corroboration is the gateway contract's own sentence: an inventory the credential in effect could not see is an empty tuple. Two runs recorded with credential_present=0 are not independent evidence of absence — nothing saw the inventory either time — yet they satisfy the counter exactly as two credentialed runs do. The route is deterministic and reproducible without any credential, so this is reachable on an unauthenticated machine. It does not re-open I-000187 (one observation still cannot admit a part); it weakens the strength of the second.
- **Acceptance**：Either exclude runs with credential_present=0 from the confirmations count (with the resulting consequence stated: an anonymous harvest can never complete exhaustion, so such parts stay out of the paid branch until a credentialed run sees them empty), or record explicitly that an anonymous observation may corroborate and why. Whichever is chosen, the empty_inventory_confirmations CTE in schema-transcripts.sql and the test that pins the filter must move together, since the filter is what the corroboration rule reads.
- **Registered**：2026-10-03T20:28:03.862Z
- **Revision**：1

### I-000013 [low] (review-obligation)

**`schedule` (and `campaign`'s batch) drive the same stage-attempt ledger but keep the old behaviour the plan removed from `run`: a SIGTERM during them leaves no run-ledger record, and `_cmd_schedule`'s record write still swallows its failure with `except Exception: pass`.**

- **Impact**：bilibili-asr-archive/src/bili_asr/cli.py — `_cmd_schedule`'s record write (`except Exception:` + `pass`, now at cli.py:2758-2774 — the registered ~L2716-2719 was a pre-fix offset) and the interruption coverage of the `schedule` entry point; `campaign.py` shares `RunCoordinator`/`run_batch` but writes no run-ledger record at all. The interruption helpers exist at module level (cli.py:2331-2367 `_interruptible_run`, :2370-2377 `_signals_ignored`, :2380-2401 `_partial_run_state`, :2404-2422 `_write_run_record`) but reuse is **parameterisation, not a drop-in call**: `_write_run_record` hardcodes `command="run"` (:2420) and its parameter list cannot carry the `last_api_error_code` (:2768) or `cursor_snapshot` (:2770) that `_cmd_schedule`'s record passes. A third run-record writer also exists and is named by no row: `_cmd_pilot` writes its own record via `RunLedger` (cli.py:1974-1990).
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000014 [low] (review-obligation)

**A `run` killed **before** its interruption guard is installed leaves no record: `started_at`/manifest load/scope resolution/client construction/banner prints all precede `_interruptible_run()`, and a SIGTERM there dies on the default disposition with no run-ledger row.**

- **Impact**：bilibili-asr-archive/src/bili_asr/cli.py — everything from `_cmd_run`'s entry (manifest load, `--scope`/`--limit` resolution, `BiliClient`/`RunCoordinator` construction, the two banner prints) up to the guard's installation. The new tests all synchronise after the banner, so this span is never exercised.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000015 [low] (review-obligation)

**`_partial_run_state` decides which attempts belong to this run by **lexicographic comparison of formatted timestamps** (`attempt['started_at'] >= started_at`), and `utc_now_iso` emits an optional fractional part — so when one side has a fraction and the other does not, the string order inverts (a run whose start lands on a whole second can admit a previous run's attempt or drop one of its own).**

- **Impact**：bilibili-asr-archive/src/bili_asr/cli.py `_partial_run_state` (the `started_at >= started_at` membership test) and its docstring. The predicate also silently rests on the archive single-writer invariant, which the docstring does not name.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000016 [low] (review-obligation)

**The interruption record is preserved across the whole coordinator unwind, but **not** universally: a second `SIGINT` landing inside the run body's `except KeyboardInterrupt` clause *after* the exception match and *before* the ignore pair is installed leaves `interrupted`/`exit_code` still `None`, so the `finally` fails all three guards and writes no record — the exit is then a propagating `KeyboardInterrupt` (a subprocess probe returns -2 — signal-killed with a traceback — so a shell still reports 130, but it is not the run body's own `return 128 + 2`).**

- **Impact**：bilibili-asr-archive/src/bili_asr/cli.py — the run body's `except KeyboardInterrupt` clause (the window between the clause matching and `_ignore_interruption_signals()`), and the `finally`'s three guards that decide whether a record is written. The unwind *outside* that clause is safe: a second Ctrl-C there is caught by the same clause, the record is still written exactly once and the exit is still 130.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000017 [low] (review-obligation)

**Five of the six Chinese homophone hotwords (自在 变易 此在 感性 实存) remain unverified in their *benefit*: the 2026-09-18 A/B exercised only 扬弃 — on 《逻辑学》第二讲 (BV1H69sB6EeF:p0) 自在/此在/变易 occur in neither the correct nor the homophone form and 感性 (4) / 实存 (3) are identical across both arms, so the measurement is a null on those five, not a confirmation.**

- **Impact**：bilibili-asr-archive/src/bili_asr/asr.py DEFAULT_HOTWORDS — the five terms 自在 变易 此在 感性 实存 (扬弃 is measured and stays). The pairing table at asr.py L156-161 is the definition to count against, and the season-run error census remains the harm to weigh: 自在 40 correct vs 13 wrong, 变易 0 vs 7, 此在 4 vs 3, 感性 12 vs 3, 实存 17 vs 3. Product-side wording sync: `bilibili-asr-archive/README.md` (the hotword paragraph) and the DEFAULT_HOTWORDS comment in `bilibili-asr-archive/src/bili_asr/asr.py` still tell the reader that the benefit of all six terms is UNVERIFIED and cite the row R3, which is now closed with 扬弃 measured — those two sentences must be re-pointed at this row and at the measured/spelled-out facts.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000019 [low] (review-obligation)

**`coverage_report._read_manifest` keeps a latent second judgement on `manifest_duplicate_work_id`: it spells the raw literal and sets `valid = False`, i.e. ordinary append-only history as malformed. Unreachable today (zero call sites) but it would re-open the R2 defect the moment the helper gains one.**

- **Impact**：bilibili-asr-archive/src/bili_asr/coverage_report.py:322-324 (helper `_read_manifest`, L286-329). The spec sanctions retention in two places — §2 (note) and §3 item 4 — not in a "§3.4" (that section does not exist; corrected 2026-09-18 after qc3-S4). The live sites are the shared set at sidecar_projection.py:190 and its three by-name consumers (integrity.py:230, coverage_report.py:74, cli.py:1289 (drifted +15 since registration; the subtraction is `manifest_diagnostics - ORDINARY_HISTORY_DIAGNOSTICS`)).
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000020 [low] (review-obligation)

**The manifest/attempt projection is duplicated verbatim between `CoverageReport.build` and `cli._cmd_coverage_quality`, so one ordinary-history code must be remembered in two files and the two copies can drift — the asymmetry between them is what made the original three-reader disagreement possible.**

- **Impact**：bilibili-asr-archive/src/bili_asr/cli.py:1280-1301 (drifted +15 since registration) against bilibili-asr-archive/src/bili_asr/coverage_report.py:65-105. The locked spec fixes the *set* and the three reader sites, not the shared projection, so deduping is outside this plan's shape.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000021 [low] (review-obligation)

**The forensics hook's log path is still writable through a symlinked parent directory: `O_NOFOLLOW` refuses only a symlink in the final path component, so a pre-existing symlinked `bilibili-asr-archive/.tb/` is followed — the exact hole the plan-QC finding named is improved (no-follow on the file, mode 0600) but not closed.**

- **Impact**：bilibili-asr-archive/tests/conftest.py (the guarded append path added by the fix wave, commit a85ffd5). Closing it needs either a directory-walk O_NOFOLLOW open or an lstat pre-check on `.tb/` — deliberately outside the fix wave's assigned shape.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000024 [low] (review-obligation)

**The four-product-path tuple now has **three** homes — `archive.py:18` (`_REQUIRED_ARTIFACT_KEYS`), `cli.py:1311/1315` (`_PRODUCT_PATH_KEYS`), `transcript_projection.py:88` — and **no test binds any pair**, while `archive_bundle_complete` refuses a mismatched key set (`archive.py:173`): a drift makes every published bundle unreadable to the completeness reader.**

- **Impact**：The three tuple declarations and the missing binding test. Seats 1 and 3 disagree on reachability (seat 3 holds the relative-root half unreachable because `archive.bundle_paths` has one production caller at `archive.py:487`) — the duplicate-home half stands unrefuted.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000025 [low] (review-obligation)

**The UTC date rendering `strftime("%Y-%m-%d", gmtime(pubdate))` is **copy-pasted** at `cli.py:1471-1473` and `transcript_projection.py:264` rather than shared the way `duration_s_from_ms` is: a drift would put the published md filename and the row's `pubdate_str` out of step.**

- **Impact**：The two call sites only. **Corrected at seat 1's re-review (2026-09-20):** the row's original second half — "the module docstring overclaims that each shared rule has one home" — is **not** true: `transcript_projection.py:33-37` scopes its claim to the shared rules that *are* imported, which is accurate. No docstring change is owed; only the duplication stands.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000026 [low] (review-obligation)

**`already_published` is probed at the **write base** while the row stores **root-relative** paths, so re-running with a different `--artifact-root` republishes and **re-points the row's four paths**; and a transient probe read error (EIO/ESTALE/WebDAV timeout) is read as `not published`, re-publishing over a good bundle and opening the marker-invalidation window (`archive.py:239`) — bytes stay identical, but the published state the predicate exists to protect is lost. Neither behaviour is disclosed in `--help` or contract §11.**

- **Impact**：The `already_published` predicate's base and its error semantics, plus the two disclosure surfaces. The root-change question is a **product decision** (is changing the artifact root supposed to re-point an archived row?) and is why this is registered rather than fixed in a fix wave. **Measured 2026-09-22** (E2E `e2e-23191782-subtitle-publish-webdav`, findings F-2 and A7(iii), target host): publishing one work to a second artifact root manifests as an **appended byte-identical row**, not an in-place re-point — the manifest went from 90 to 91 raw rows with the new pair for `BV1zz5zzFENq:p0` comparing equal under a key-sorted serialization, and the row schema carries **no field naming a root or base at all** (`bvid, cid, duration_s, language, md_path, page_index, pubdate, pubdate_str, raw_path, source, srt_path, status, title, txt_path, work_id`). So the two publications are indistinguishable in the manifest rather than one overwriting the other's paths, and the archive cannot attribute a published row to the root holding its products.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000028 [low] (review-obligation)

**Corpus-scale cost in the new path: every `already_published` decision **content-reads and SHA-256s all four artifacts** (no size cap), so an idempotent re-run re-reads the entire published corpus over the mount (≈10 GB for 3 000 parts at ≈3.5 MB/bundle) and a *published* candidate re-reads what it just wrote; and `ManifestStore.upsert` re-reads and re-validates the whole JSONL per candidate (`manifest.py:280`, `:162-168`) → O(N²) in the number of candidates, an exposure new to this command because it publishes thousands of bundles in one process.**

- **Impact**：The candidate loop's per-candidate cost, not the correctness of the completeness check (which seat 2 verified cannot accept an incomplete bundle).
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000029 [low] (review-obligation)

**Four smaller items from the same tri: (a) `--limit-parts` bounds the *selection* but not the **read**; (b) there is no per-candidate I/O timeout, so a hung mount blocks the run while it holds the writer flock (every other writer then sees `archive_busy`), and stdout is block-buffered when piped; (c) the duplicate product-key tuple drifts **silently and expensively** (a drift loses the fast path, so every run republishes the corpus and still exits `0`) — pin it with a one-line equality test; (d) `_winner_key` raises an uncaught `KeyError` on a fourth `source_kind`, and the entry construction (`format_work_id`, `time.gmtime`) sits outside the per-candidate guard so one bad row aborts the run.**

- **Impact**：Small, independent hardening items in the command and the projection service; (c) overlaps R3's tuple duplication and is closed by the same test.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000030 [low] (review-obligation)

**Seat 2's four remaining Suggestions (its F-005/F-006/F-007/F-010 class) plus the bare-`bvid` shadowing note RP-1: accepted with no action — each is Suggestion-grade with nil live risk, and the raising seat itself did not make any of them a gate condition.**

- **Impact**：No action is owed. The row exists so the register's completeness claim is true and so a future reader can find these items without re-reading the seat report.
- **Acceptance**：accept
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000032 [low] (review-obligation)

****A source-reducing formatting step was not count-guarded, and it silently narrowed what six reviewers could see.** The alignment table I built for the proofreading wave assigned each caption cue to an ASR-derived time block by its **midpoint**; a cue whose midpoint fell between blocks (i.e. inside an ASR VAD gap) belonged to no block and was **dropped from the table entirely** — 251 of 9607 cues (2.6%), with no `⟨空缺⟩` marker and no count check.**

- **Impact**：Verification methodology, not product code: any transformation that sits **between a source and the person or agent judging it** and can lose source text without saying so. This instance was ad-hoc tooling for one E2E, so the durable form of the lesson is a rule, not a patch: a source-reducing step must (a) account for every input item (count in == count out, with an explicit bucket for “not attached”), (b) never render a dropped item as silence. It sits in the same family as `{KNOWLEDGE_DIR}/best-practices/premise-freshness-before-lock.md` (a premise inherited rather than re-verified) and the E2E's own `absence-assertion-negative-control` discipline. Closers: record the rule where the project's verification methodology lives (a best-practice note or the E2E contract), or nothing — accepted as a closed one-off with the measurement above as its record.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-22
- **Revision**：1

### I-000034 [low] (review-obligation)

**`tests/test_check_asr_env.py::test_a_cwd_torch_py_does_not_change_the_verdict` is deterministically red on the project's own GPU host: it asserts the whole captured stderr is equal across two child runs, and ROCm's own startup warning (`agent.cpp:608] sysfs nodes path '/sys/class/kfd/kfd/topology/nodes' does not exist`) embeds a per-invocation timestamp, so the two captures can never be equal there.**

- **Impact**：`tests/test_check_asr_env.py`'s stderr expectations, and by class every test that compares a captured subprocess stream verbatim: the ROCm warning is host runtime noise, not the verdict under test. Consequence: on the only machine where this project's ASR actually runs, the suite is red for a reason that has nothing to do with the product, so a genuine failure in the same file is indistinguishable from this one.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-22
- **Revision**：1

### I-000035 [low] (review-obligation)

**A venv can hold a working-looking `bili-asr` console script with no distribution behind it: both `<repo>/bilibili-asr-archive/.venv/bin/bili-asr` and `/root/gpu-venv/bin/bili-asr` existed on the target host while `import bili_asr` failed from every cwd, so the "the repo's virtualenv is an editable install" invariant that the false-evidence guard in `{KNOWLEDGE_DIR}/testing-patterns/worktree-test-invocation.md` rests on silently did not hold.**

- **Impact**：Environment drift detection, not product code. The documented invocation contract (`worktree-test-invocation.md`: "the repo's virtualenv ... is an *editable* install: its `.pth` hard-codes the primary checkout's `src` path") has nothing that re-establishes or reports the condition, and its failure mode — `ModuleNotFoundError: bili_asr` out of the very command the README publishes — reads as a code defect rather than a broken environment. Two candidate closers: a documented venv-rebuild step that ends in the editable install, or the cheap resolved-`bili_asr.__file__` probe recorded where that document already asks for it. Distinct from row `e2e-23191782-longform-pair-webdav . R5`, which covers `check-asr-env`'s helper under an installed *wheel* layout: an editable install still resolves the helper under `parents[2]`, a wheel never will.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-22
- **Revision**：1

### I-000036 [low] (review-obligation)

**A store-based `status` cannot see a root's pre-store products: `/mnt/e/asr-archive-20` holds 3 `archived` parts (audio plus the four product files each) and a 20-row effective manifest, while its `archive.db` carries `transcripts = 0` and `audio_objects = 0`, so `status --archive-root /mnt/e/asr-archive-20` reports **63 pending**.**

- **Impact**：Operator-facing state surfaces on an archive root whose products predate the SQLite product tables (`iter-2026-09-subtitle-transcript-sqlite`). **Measured limit — this is not duplicated work:** `derive-manifest --help` documents its own policy ("a row the chain already holds is left alone") and the bridge is additive over *manifest* rows, so the 20 effective rows are untouched and only the remaining 43 parts would be appended; the cost of the disagreement is a misleading read (an operator sees 63 pending on a root where 3 parts are archived and 17 hold audio) and whatever is concluded from it, not a re-download or re-ASR. Two candidate closers: a recorded decision that pre-store roots are read through their manifest and not the store — with `status` saying so on such a root — or an adoption path that writes the on-disk products into the store.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-22
- **Revision**：1

### I-000040 [low] (review-obligation)

****The archive holds two engines' text, by decision, and the record now lives where a reader of the frontmatter will look.** Three transcripts under `/mnt/e/asr-archive-20/` (`BV1P8No6mEsB`, `BV1S8hA6MEvy`, `BV1fD3o69EiP`) still carry `asr_model_name: FunAudioLLM/Fun-ASR-Nano-2512` because the Qwen3 rebuild was a hard switch and the archive was not re-transcribed (decision D12). This row is the **supporting** surface named by compass C8; the authoritative statement is the `### An archive can hold two engines' text, and that is decided, not broken` subsection of `bilibili-asr-archive/README.md`'s provenance material.**

- **Impact**：Any corpus-wide reading that spans the engine boundary measures two different decoders. The sharpest instance is the hotword list: every measured figure in the README's `The corpus vocabulary, and which engine measured it` subsection belongs to the retired checkpoint, so re-measuring under the shipping engine is its own work item rather than an assumption. Bounded deliberately low: nothing is broken, no transcript mixes two engines, and the frontmatter makes each file's engine legible without a guess.
- **Acceptance**：accept
- **Owner**：@project-manager
- **Registered**：2026-09-26
- **Revision**：1

### I-000043 [low] (review-obligation)

**The project's headline coverage figure (150/1730, 8.7%) originates on another machine and is not reproducible from this checkout, whose store supports 6/1730 (0.35%).**

- **Impact**：The project's evidence base rather than product code. Any coverage number an operator or a future plan inherits must name the host that produced it; the two figures differ by roughly 25x and only the local one is verifiable from this checkout. It affects any plan that sizes work from 'how much is left', including the coverage-closure question this review was answering.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-25
- **Revision**：1

### I-000045 [low] (review-obligation)

**The audio-inventory plan's Task 1 is SUPERSEDED and no longer executable as written: its `## Interfaces` names `record_audio_object` / `link_part_audio` / `AudioObjectRecord`, none of which exist in the tree. The real seam is `MediaQueueRepository.mark_audio_acquired` (keyed on `storage_key`, not `sha256`), shipped by other lifecycles (PR #21 2696711 / PR #24 662d9ca). Task 2 consumes that and its heading is annotated SUPERSEDED, but Task 1's own Steps remain in the plan and would mislead an implementer who read them without the annotation. Close by rewriting Task 1 to describe the shipped seam, or by deleting it and recording that the seam arrived elsewhere.**

- **Impact**：`{PLAN_DIR}/20260926-audio-inventory.md` Task 1's `## Interfaces` text against the shipped seam `MediaQueueRepository.mark_audio_acquired` (src/bili_asr/storage/database.py:1593, keyed on `storage_key`)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000050 [low] (review-obligation)

**CONTRACT WORDING, not a code defect. Section 3.1 words `recorded` as "a manifest candidate that had NO audio_objects row and now has one", but the fix round had to decide a case the wording does not cover: a row that EXISTS and does NOT match (a file replaced in place). The implementation counts that as `recorded`, because the run wrote the content afresh -- calling it `already` would assert the "and matched" the same section requires of that counter, and counting it as neither would hide a rewrite. The next unchanged run then reports `already`, which is the convergence F8 asked for. The contract sentence should say so explicitly (e.g. "recorded: a candidate this run wrote -- no row, or a row that did not match"), or rule the other way. Also still open from A-R1: a present-but-unreadable file fits no counter, now named in the outcome instead.**

- **Impact**：the audio-retention contract §3.1's `recorded` wording — contract prose, not code; a present-but-unreadable file is the case that still fits no counter
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000052 [low] (review-obligation)

**The audio-inventory plan's Task 3 (two narrow coverage gaps in the retention and reclaim surfaces) was NEVER EXECUTED — 0 of 5 Steps — and was WAIVED at close rather than run. It is XS and its subject already passes: AC 5 is met by test_audio_retention_policy.py + test_audio_reclaim.py (13 passed, 2 skipped), so the task only adds two further characterisation cases over working behaviour. Recorded because the plan row previously carried `Done / 100%` with 10 of 15 Steps unchecked, which overstated the task level — the same false-completion class the PM corrected in other writers' records during this iteration. The plan now annotates Task 3 DEFERRED in place with its reasoning, and Task 1 is annotated SUPERSEDED. Close by either writing the two cases (XS) or leaving the waiver as the recorded decision.**

- **Impact**：`{PLAN_DIR}/20260926-audio-inventory.md` Task 3 (0 of 5 Steps) + tests/test_audio_retention_policy.py, tests/test_audio_reclaim.py (AC 5 already green: 13 passed / 2 skipped)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000054 [low] (review-obligation)

**tags_by_video run cache unbounded (bounded by corpus size; revisit on growth).**

- **Impact**：the metadata-enrichment plan surface (src/bili_asr/services/metadata_ingest.py, storage/*)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000055 [low] (review-obligation)

**Duplicate-page resume re-fetches tags already collected in the aborted run (redundant cost; replace-set write idempotent).**

- **Impact**：the metadata-enrichment plan surface (src/bili_asr/services/metadata_ingest.py, storage/*)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000058 [low] (review-obligation)

**D16 rule restated as long prose at 4+ comment layers (gateway/protocol/_observed_tag_sets/record_page) — drift hazard; consolidate on refactor.**

- **Impact**：the metadata-enrichment plan surface (src/bili_asr/services/metadata_ingest.py, storage/*)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000059 [low] (review-obligation)

**record_page lets the FK raise for a tag set whose bvid was not upserted in-txn (latent sharp edge for future callers; unreachable via sole caller).**

- **Impact**：the metadata-enrichment plan surface (src/bili_asr/services/metadata_ingest.py, storage/*)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000060 [low] (review-obligation)

**Run-scoped observed_author freezes on first named page; restamps users.updated_at per page without new information (D15-consistent side effect).**

- **Impact**：the metadata-enrichment plan surface (src/bili_asr/services/metadata_ingest.py, storage/*)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000061 [low] (review-obligation)

**No end-to-end rerun test where stored tags survive a degraded second-run fetch (D16 composed path covered only unit-wise).**

- **Impact**：the metadata-enrichment plan surface (src/bili_asr/services/metadata_ingest.py, storage/*)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000069 [low] (review-obligation)

**The `importorskip` gate returned in a NEW file: `tests/test_raw_characters.py:396-397` gates on numpy/soundfile, and its docstring + a guard-order comment both still describe those as an optional `[asr]` extra whose absence should SKIP — a stance this plan deliberately reversed.**

- **Impact**：`tests/test_raw_characters.py:388-397`. The file genuinely needs the two modules (`np.zeros(...)`, `monkeypatch.setattr(soundfile, ...)`), so the guards are inert on any host that can run the file at all.
- **Acceptance**：accept
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000071 [low] (review-obligation)

**Contract documents still state the pre-revision key counts (frontmatter 24, projection table nine)**

- **Impact**：the projection contract §4.1 table (nine keys) and the metadata-coverage contract schema-evolution section ("exact ordered list of 24 keys"); the live counts are 25 and ten after the D4/D5 revision
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000073 [low] (review-obligation)

**A third contract outside this iteration still states the pre-revision key count (transcript-projection §4.1 "exactly these nine keys")**

- **Impact**：`{ITERATION_DIR}/iter-2026-09-transcript-projections/specs/transcript-projection-contract.md` §4.1 (~L206, "exactly these nine keys, and no others") — a third iteration's contract prose; no product file
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000076 [low] (review-obligation)

**The D-2 exposure, registered not fixed: `part_title` and `tag_name` ride the same page-level fan-out and the same `_text` discipline as `description` did, so a single multi-line value in either field fails the WHOLE page and — absent `--skip-failed-page` — wedges the cursor permanently. This plan deliberately did not extend the `desc` absence rule to them (no upstream observation of a control character in either field; `plan` Sec. Out of scope), but the class is now proven real rather than hypothetical by E1-E5.**

- **Impact**：src/bili_asr/sources/bilibili_api_gateway.py `_read_optional_text` call sites for `part_title` and `tag_name` (both still reject a control character as a bounded shape error), against the page-level fan-out that turns one bad item into a whole-page failure
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-30
- **Revision**：1

### I-000077 [low] (review-obligation)

**`--start-page N --skip-failed-page` with N below the stored cursor REWINDS the resume point: the skip branch writes `next_page = page_number + 1` with no comparison against the value already stored, so a deliberate rewind plus a skip can move the next `--resume` backwards and re-parse the intervening range.**

- **Impact**：src/bili_asr/services/metadata_ingest.py:417 (the skip branch's `next_page=page_number + 1`) versus the flag's own claim of 'forward progress'. NOTE the same unconditional write exists on the SUCCESS path at `:656`, so this is `--start-page` semantics rather than a defect the skip branch introduced — `--start-page` already means 'enumerate from here', and the cursor ends where that enumeration got to.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-30
- **Revision**：1

### I-000080 [low] (review-obligation)

**list_queue_gaps validates limit with inline isinstance instead of the module _integer convention.**

- **Impact**：src/bili_asr/storage/{schema-transcripts.sql,database.py,models.py} + tests/test_storage_*.py
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000081 [low] (review-obligation)

**mark_transcript_stored validates after part lookup while mark_audio_acquired validates before — same write surface, two orders.**

- **Impact**：src/bili_asr/storage/{schema-transcripts.sql,database.py,models.py} + tests/test_storage_*.py
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000082 [low] (review-obligation)

**Pre-transaction validation can leave an open read txn on the failure path (absorbed by known callers).**

- **Impact**：src/bili_asr/storage/{schema-transcripts.sql,database.py,models.py} + tests/test_storage_*.py
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000083 [low] (review-obligation)

**v_missing_transcript omits processing_status deliberately (gone part stays transcribable) — cross-view contract undocumented beyond one comment.**

- **Impact**：src/bili_asr/storage/{schema-transcripts.sql,database.py,models.py} + tests/test_storage_*.py
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000084 [low] (review-obligation)

**Attempt-history cost scales with unbounded append-only acquisition_attempts (served by existing index today).**

- **Impact**：src/bili_asr/storage/{schema-transcripts.sql,database.py,models.py} + tests/test_storage_*.py
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000086 [low] (review-obligation)

**The reader pair still disagrees on the DECLARED axis: coverage gates its inferred candidates on `inferred = not values` while verify's §2f widening is unconditional**

- **Impact**：src/bili_asr/quality.py:418-426 (_artifact_paths inferred gate) vs src/bili_asr/integrity.py:415-443 (unconditional raw_candidates)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000087 [low] (review-obligation)

**coverage --quality cost grows ~2.5x on undeclared in-flight populations because the narrowing offers absent inferred candidates only when they escape**

- **Impact**：src/bili_asr/quality.py:455-470 (the escape-gated offer) with _escapes_every_base
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000090 [low] (review-obligation)

**Stale test comment claims 'the brief forbids editing integrity.py' while this branch edits it; misleads future maintainers about the triplicated status-set constant.**

- **Impact**：src/bili_asr/{integrity.py,quality.py,cli.py} + tests/test_{integrity,cli_exit_contract,quality}*.py + README
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000091 [low] (review-obligation)

**In-flight status set literal exists in cli.py / integrity.py / coordinator.py with only pairwise drift guards.**

- **Impact**：src/bili_asr/{integrity.py,quality.py,cli.py} + tests/test_{integrity,cli_exit_contract,quality}*.py + README
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000092 [low] (review-obligation)

**quality.py: two add-sites can both add artifact_missing — attribution ambiguous (set dedupes output).**

- **Impact**：src/bili_asr/{integrity.py,quality.py,cli.py} + tests/test_{integrity,cli_exit_contract,quality}*.py + README
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000093 [low] (review-obligation)

**integrity.py: continue after escaped_raw flag is practically unreachable; kept for documentation intent.**

- **Impact**：src/bili_asr/{integrity.py,quality.py,cli.py} + tests/test_{integrity,cli_exit_contract,quality}*.py + README
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-27
- **Revision**：1

### I-000096 [low] (review-obligation)

**PRE-EXISTING, NOT INTRODUCED BY SHAPE A: a target FILE that is a symlink is replaced rather than refused (`os.replace` semantics in archive._replace_at). Reproduced identically against the four-kind-dir layout on main, and the linked file's contents are left untouched, so a link is replaced rather than followed -- not an out-of-root write. Recorded so it is not re-discovered and reported as a regression of this change.**

- **Impact**：src/bili_asr/archive.py `_replace_at` (:121, `os.replace` at :122) — a target file that is a symlink is replaced rather than refused
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000097 [low] (review-obligation)

**NO {PLAN_DIR} PLAN FOR THE LAYOUT MIGRATION. The survey stated no migration plan could be written until decision L1 landed; L1 landed on 2026-09-28 AFTER this iteration had closed, so the change shipped as a branch plus PR #26 instead of a planned task breakdown. The decision and its delivery are recorded in specs/output-layout-options.md §5 and this iteration's delivery-compass.md. Recorded so the absent plan is not read as an omission.**

- **Impact**：the absent `{PLAN_DIR}` migration plan for the layout change — a planning gap, not product code
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000101 [low] (review-obligation)

**EVIDENCE GAP: the CLI half of --asr-root/--caption-root has no behavioural test, and an empty root silently becomes the cwd**

- **Impact**：cli/publish.py:237-239 (a docstring claiming every refusal names the path it looked at), cli/publish.py:256-257 (flag forwarding), cli/parser.py:323,331 + proofread.py:651-659 (no normalisation of the two new roots)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-10-01
- **Revision**：1

### I-000106 [low] (review-obligation)

**`publish-transcripts` is a **silent no-op** on an audio-only root — six invocations exit 0 with `candidates=0 published=0 already_published=0` — because its range is 'every stored part that holds a transcript' and the `asr` stage already wrote the bundles itself; an operator following the documented caption-path sequence on the audio path sees success and no publications.**

- **Impact**：The command surface and the two branches' division of labour. The behaviour is consistent with the help text and with this bucket's R3 (an audio-only root has no stored transcripts, so the command has no candidates) — the gap is that the previous E2E established `publish-transcripts` as *the* publication step, and on the audio path that step is a no-op that reports success. Two closers: the `--help`/docs say which stage publishes on each branch (the `asr` stage for the audio path, `publish-transcripts` for stored transcripts), or the command reports that it found no candidates *because* the branch publishes elsewhere. Closing condition: one of the two is published and a case pins the audio-path expectation.
- **Acceptance**：defer
- **Owner**：@product-manager
- **Registered**：2026-09-22
- **Revision**：1

### I-000108 [low] (review-obligation)

**A part that already carries an **AI caption** cannot be put through the audio→ASR branch at all: `derive-manifest` excludes it by design (the queue is 'no transcript'), and no shipping flag overrides that, so a local ASR transcript cannot be produced for a captioned item — and the audio branch of the two most recent iterations stays unverified on a live row.**

- **Impact**：The audio/ASR selection surface (`download-audio --missing-subs`, `asr --pending`, `run --scope pending`, `derive-manifest`'s predicate) for parts that hold a stored transcript. Not a defect of the cap: 'subtitles first, local ASR as fallback' is the published design and every command behaved as documented. What is unverified because of it: the artifact-root product placement (`/mnt/123pan`) on a real archived row, and the audio→ASR path of `iter-2026-09-artifact-root` / `iter-2026-09-queue-bridge` on live data. The 2026-09-17 season run remains the only live audio evidence and predates both iterations.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000109 [low] (review-obligation)

**A full channel enumeration is not reachable while one upload-list page is under upstream risk control: `fetch-meta` stops at the blocked page with exit 2 and a preserved cursor (correct behaviour), but there is no bounded cross-page retry/backoff and no way to step over a blocked page other than knowing to pass `--start-page`.**

- **Impact**：`fetch-meta`'s page loop and its operational surface only. The product's failure handling is correct and resume-safe (bounded scalar code, cursor unchanged at `next_page=3 state=ready`, nothing lost) — this row covers the missing *recovery* affordance, not a bug.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000110 [low] (review-obligation)

****An E2E or development premise inherited from a stored snapshot goes stale silently**: this run's scope asserted the audio branch from a three-day-old manifest while the live source had begun serving AI captions for both items, and the plan compounded it by allowing two outcomes in one scenario (A3) while its downstream scenarios assumed one — four of nine scenarios failed on that single change, none of them a defect.**

- **Impact**：Plan and scope authoring, not product code: (i) any premise about upstream or store state that a plan or an E2E scope inherits from an artifact rather than from a live probe; (ii) any scenario whose expected value is branch-conditional while its downstream scenarios are not written conditionally. Both rules generalise beyond this project's video corpus.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000111 [low] (review-obligation)

**`check-asr-env` **cannot resolve its helper in an installed layout under either anchor**: only `bili_asr` is packaged, so `scripts/check_asr_env.py` is absent from a wheel/editable install and both `parents[2]` and `parents[3]` miss — the command then answers `no check script found` and points the operator at a path variable rather than at the real cause.**

- **Impact**：The `check-asr-env` handler's script resolution and the packaging decision behind it. Two candidate closers: ship the helper as package data and resolve it through `importlib.resources` (works in every layout), or keep it source-tree-only and make the refusal name that fact ('this build does not ship the host self-check') instead of listing candidate paths. The exit taxonomy is unaffected either way.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000117 [low] (review-obligation)

**Latin tokens glue inside a cue when Nano omits their leading space: `_token_cues` builds the cue text with `"".join(parts)`, while the space-repair rule (`_join_text`) is applied only when absorbing an undersized cue and when handing a closing mark back — so the third place that needs it, intra-cue concatenation, glue words together (measured: 'asME IDEA', 'bothAND', 'questionITSELF', 'anITEM').**

- **Impact**：bilibili-asr-archive/src/bili_asr/asr.py _token_cues: `parts.append(piece)` + `text = _clean_text(pending + "".join(parts))` versus `_join_text`, which is called only from `hand_back()` and from the undersized-cue absorption path. `_join_text`'s own docstring already declares the phenomenon and the rule ('Nano emits an English phrase as several tokens and does not always carry the leading space'), so this is the rule applied in two of the three places it is needed. Chinese text is unaffected, which is why 13 of 14 items show none.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-17
- **Revision**：1

### I-000119 [low] (review-obligation)

**`coverage --quality`'s cue denominator is exactly twice the stored segment count for every published row: 4636 cues for a row with 2318 stored `transcript_segments`, and 19214 for the six-row total of 9607 — so the quality surface's cue count does not agree with the transcript store it is reported against.**

- **Impact**：`coverage_report.py`'s cue accounting against `storage`'s `transcript_segments`, and the naming of the reported field. Two readings are indistinguishable from the surface and `--help` does not say which is intended: either `cue_count` deliberately sums two artifact families (the run's reason vocabulary is per-family, so a doubling may be a designed cross-family total) or one cue is counted twice. Closers: the definition is documented and the field is named for it (per-family counts, or a `cues_by_family` breakdown), or the double count is removed. Closing condition: a test pins the relationship between `total_cues` and `transcript_segments` for one published row.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-22
- **Revision**：1

### I-000120 [low] (review-obligation)

**`verify` and `coverage` exit 1 on a healthy archive that merely still has unprocessed rows: 84 defects — all `retryable_incomplete`, all on the 84 `needs_audio` rows and **none** on the six published rows — plus the diagnostic `missing_attempts_sidecar` are collapsed by the CLI's `0 if not defects and not diagnostics` rule into one non-zero status that is indistinguishable from a corrupt store.**

- **Impact**：The exit contract of the two readers, not their findings. Row `e2e-23191782-season-7686105 . R2` (high, RESOLVED) removed a **false** malformed verdict from these readers; this row is what remains after it — a **true** observation (work is pending) sharing one exit code with the unsafe outcome (the archive is damaged). A curation loop that gates on `verify` therefore cannot distinguish 'nothing processed yet' from 'stop and repair'. Two closers: a distinct exit code (or a `--strict` / `--pending-ok` shape) separating pending work from defects, or a recorded decision that a curated root is expected to be fully processed so the overloaded code is intended — with the `missing_attempts_sidecar` diagnostic's own status decided in the same breath. Closing condition: the exit contract is written down and a fixture pins both states.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-22
- **Revision**：1

### I-000121 [low] (review-obligation)

**The write path's **silent no-upsert** hazard is unreachable only by construction: `audio._mark_audio_ok` still returns without upserting when no base confines the path, so a future caller that wires the wrong base would turn a misconfiguration into an endless re-download instead of an error. Two load-bearing comments also understate their reasons.**

- **Impact**：`audio.py`'s record-time confinement, the coordinator's `download_kwargs` conditional, and `audio_reclaim.py`'s per-base loop. Not a live defect: the shipped call graph cannot reach M1, and  **M3 was superseded during the plan (QA finding F-1, 2026-09-19):** fix wave 1 of the plan's QC reversed that asymmetry - `audio_reclaim.py` now remembers the per-base `ValueError` and continues to the next base, re-raising only when no base handled the recorded value, pinned by `test_a_symlink_at_the_configured_base_does_not_abandon_the_other_copy`. This row now covers **M1 (raise loudly instead of returning silently) and M2 (say why the conditional is load-bearing)** only; the anchor `audio_reclaim.py:76-80` quoted here at registration sits inside that fix.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-19
- **Revision**：1

### I-000124 [low] (review-obligation)

**Both iteration closes of 2026-09-19 wrote a **terminal workflow snapshot without `ended_at`**, which the engine's own reader refuses: while the root `status.json` registry is empty (removal-at-terminal), the selection fallback resolves the newest terminal snapshot, so the invalid document made every session's engine state read return `workflow.selection.snapshot-unreadable` (no plan rows, leases, residuals or branch anchors visible in the digest) until it was repaired on 2026-09-20.**

- **Impact**：The Phase 6 close procedure in this repository, i.e. `.mstar/workflows/<id>/snapshot.json` writes at close. Not a product defect and not a defect of the engine: the engine's contract is explicit (a terminal status requires `ended_at`). The repair on 2026-09-20 set `ended_at` on both snapshots (both now validate clean), so the read path is healthy; what remains is the recurrence risk, because this repository has no `mstar` CLI installed and therefore writes these documents by hand.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-20
- **Revision**：1

### I-000129 [low] (review-obligation)

**transcript_fts_index_meta is written every build but never read; indexed_count stores per-invocation rows, not a total.**

- **Impact**：src/bili_asr/search_index.py `STORE_INDEX_META_TABLE` = `transcript_fts_index_meta` (:976; written at :1428/:1433, never read)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000130 [low] (review-obligation)

**build_run_record accepts hotwords_dropped but no caller populates it; dropped tokens visible only in per-part archive provenance.**

- **Impact**：src/bili_asr/run_ledger.py `build_run_record` (:171), parameter `hotwords_dropped` (:186) and the emitted key (:207) — no live caller
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000131 [low] (review-obligation)

**cli.py grew 3871 -> 4435 lines this iteration; thin-delegation still holds, but a commands/ package extraction is the tracked direction.**

- **Impact**：src/bili_asr/cli.py (3871 -> 4435 lines this iteration) — the tracked `commands/` package extraction
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-28
- **Revision**：1

### I-000132 [low] (review-obligation)

**The derived queue cannot rotate over **failed** audio attempts: the store has no legal place to record a per-part audio outcomes, so a bounded run that keeps failing the same head will keep re-selecting it. `acquisition_attempts.outcome` is caption-only and its CHECK binds outcome to transcript_id/error_code; widening it applies to fresh databases only (CREATE TABLE IF NOT EXISTS cannot widen, and the schema header declares no migration), and `audio_objects`/`part_audio_objects` are intentionally-empty scaffolding with no writer.**

- **Impact**：The SQLite side's per-part evidence for audio/ASR, and the selection order of whatever command consumes the derived queue. This iteration's bridge is read-only on archive.db and derives rows whose only forward states are the manifest's own (`needs_audio` -> `audio_ok` -> `archived`, plus the coordinator's attempts.jsonl), which preserves rotation for a *successful* attempt and loses it for a failing one.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-19
- **Revision**：1

### I-000133 [low] (review-obligation)

**`derive-manifest`'s additive policy does not consult a **legacy bare-`bvid` manifest row**, so a part the chain already archived under that key form is appended as `needs_audio` and a bounded run re-downloads and re-runs it. The row is never rewritten (the literal promise), but the part is re-queued (the intent the plan's own criterion states).**

- **Impact**：`src/bili_asr/services/manifest_derivation.py` (the conflict lookup) and the two published surfaces that scope their additive claim to `work_id` (README's derived-queue limits; `docs/metadata-storage.md`'s boundary bullet). The behaviour is bounded, not destructive: the ASR bundle lands at the page-qualified stem, so a legacy `{bvid}.srt/.txt/.md` is not overwritten — the cost is a re-download plus a re-ASR for an already-archived part.
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-19
- **Revision**：1

### I-000137 [low] (review-obligation)

**Knowledge-doc reference lint: the engine's own `compound validate` fails across the {KNOWLEDGE_DIR} tree (was 'six of nine' when first registered; measured 2026-09-27: 13 of 22 docs, 63 violations, in only two codes — 33 `compound.reference.missing-file` + 30 `compound.reference.module-missing`)**

- **Impact**：{KNOWLEDGE_DIR}/** reference resolution, as checked by lintCompoundWrite / `mstar compound validate` (doc-level check only; the `knowledge_dir` variant additionally asserts catalog completeness against {HARNESS_DIR}/store.db, which is absent on this host and fails for that reason instead)
- **Acceptance**：defer
- **Owner**：@project-manager
- **Registered**：2026-09-18
- **Revision**：1

### I-000142 [low] (improvement)

**Metadata gateway pacing is unconditional, taxing single-bvid/small selections ~0.8-1.6s per call**

- **Impact**：Small/targeted metadata batches pay the full pacing latency floor with no burst threshold
- **Acceptance**：pacing is gated on the run's expected row count (or the small-selection latency floor is documented)
- **Owner**：project-manager
- **Registered**：2026-10-01T20:11:31.865Z
- **Revision**：1

### I-000143 [low] (improvement)

**Cleanup leftover: fix/20261002-002-asr-limit worktree+branch (dirty with env artifacts uv.lock/egg-info)**

- **Impact**：One orphaned worktree+branch remain after iter close; the fix itself is merged to main
- **Acceptance**：Discard the dirty env artifacts and remove the worktree+branch (git worktree remove + git branch -d), or leave documented
- **Owner**：project-manager
- **Registered**：2026-10-01T20:18:06.621Z
- **Revision**：1

### I-000144 [low] (improvement)

**Cleanup leftover: iteration/iter-2026-10-audit-burndown branch (merged via PR #30 but cleanup flagged unmerged)**

- **Impact**：One merged integration branch remains locally/remote
- **Acceptance**：Verify the merge (it is PR #30 merge commit 276346b) and delete the branch, or leave documented
- **Owner**：project-manager
- **Registered**：2026-10-01T20:18:07.159Z
- **Revision**：1

### I-000146 [low] (improvement)

**QC S1: 010 _now dedup left triple blank-line runs at both extraction sites**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T21:40:40.124Z
- **Revision**：1

### I-000147 [low] (improvement)

**QC S2: queue_source.record_local_transcript uses int(time.time()) not consolidated services _now()**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T21:41:44.485Z
- **Revision**：1

### I-000148 [low] (improvement)

**QC S3: 005 leaves unreachable stamped_part_ids membership guard in rebuild loop**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T21:41:44.991Z
- **Revision**：1

### I-000150 [low] (improvement)

**QC: ensure_asr_run docstring scope wording (per-source not per-invocation)**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T23:44:44.306Z
- **Revision**：1

### I-000151 [low] (improvement)

**QC: unused _sys alias + redundant local _time import in queue_source ensure_asr_run**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T23:45:17.130Z
- **Revision**：1

### I-000152 [low] (improvement)

**QC: _caption_language_from_entry omits sub_lan_doc fallback its docstrings name**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T23:45:17.672Z
- **Revision**：1

### I-000153 [low] (improvement)

**QC: write-back queue source only closed on run_batch path (contract clarity)**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T23:45:18.222Z
- **Revision**：1

### I-000154 [low] (improvement)

**QC: kind=asr acquisition runs never finished (unbounded growth, carry-forward)**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T23:45:18.803Z
- **Revision**：1

### I-000155 [low] (improvement)

**QC: local-transcript fallback language und when ASR provenance names no language**

- **Impact**：cosmetic / behavior-neutral
- **Acceptance**：addressed in a future tidy plan
- **Owner**：project-manager
- **Registered**：2026-10-01T23:45:19.333Z
- **Revision**：1

### I-000157 [low] (bug)

**test_cli_pilot fixture gap: 2 tests read manifest.jsonl a journal-only upsert never writes (same family the closeout drift-repair fixed elsewhere)**

- **Impact**：behaviour gap / red tests masking regressions
- **Acceptance**：The 2 cli_pilot tests seed the manifest snapshot (store.save()) like the drift-repair batch did
- **Owner**：project-manager
- **Registered**：2026-10-02T07:00:56.222Z
- **Revision**：1

### I-000158 [low] (improvement)

**R2-F4/S3: chunking (search_index._IN_CHUNK) had no regression pin**

- **Impact**：traceability / small behavioural tolerance; no live defect
- **Acceptance**：addressed in a follow-up tidy plan or the next iteration touching that module
- **Owner**：project-manager
- **Registered**：2026-10-02T12:53:24.124Z
- **Revision**：1

### I-000159 [low] (improvement)

**R2-F7/S5: entry_for_item raises KeyError on an out-of-band gap where the frozen helper fell back to needs_audio (no test binds the helper)**

- **Impact**：traceability / small behavioural tolerance; no live defect
- **Acceptance**：addressed in a follow-up tidy plan or the next iteration touching that module
- **Owner**：project-manager
- **Registered**：2026-10-02T12:53:24.692Z
- **Revision**：1

### I-000160 [low] (improvement)

**R1/S: _iter_valid(strict=True) is src-dead (its strict branch has no production caller)**

- **Impact**：traceability / small behavioural tolerance; no live defect
- **Acceptance**：addressed in a follow-up tidy plan or the next iteration touching that module
- **Owner**：project-manager
- **Registered**：2026-10-02T12:53:25.404Z
- **Revision**：1

### I-000161 [low] (improvement)

**R1/S: store-route meta_ok mapping + select_pending_scope override are behaviourally inert (removing both leaves the suite byte-identical)**

- **Impact**：traceability / small behavioural tolerance; no live defect
- **Acceptance**：addressed in a follow-up tidy plan or the next iteration touching that module
- **Owner**：project-manager
- **Registered**：2026-10-02T12:53:25.951Z
- **Revision**：1

### I-000162 [low] (improvement)

**R2-F8: plan/compass Done text still promises the pre-STOP scope (12 fixtures, F7+R13/R15 closed) although only the mapping shipped**

- **Impact**：traceability / small behavioural tolerance; no live defect
- **Acceptance**：addressed in a follow-up tidy plan or the next iteration touching that module
- **Owner**：project-manager
- **Registered**：2026-10-02T12:53:26.471Z
- **Revision**：1

### I-000163 [low] (improvement)

**QC: close evidence should state the full pre-existing baseline (~73 failures/5 collection errors across the non-harness suite), not only the 8 attributed ones**

- **Impact**：traceability / small behavioural tolerance; no live defect
- **Acceptance**：addressed in a follow-up tidy plan or the next iteration touching that module
- **Owner**：project-manager
- **Registered**：2026-10-02T12:53:27.038Z
- **Revision**：1

### I-000173 [low] (bug)

**AUDIT-2026-10-02R2: set_pacing_floor() has no production caller, so the small-selection pacing opt-out the delta documented is unreachable**

- **Impact**：The docstring states the enumeration entry point lowers the floor per run, but metadata_ingest never calls it; every fetch-meta call pays the 0.8-1.6s sleep, including the single-bvid selections the floor exists for. The `<= 1` guard line is therefore test-only. Registered I-000053/I-000141 cover the tag leg and the async-sleep class; this is the unwired seam.
- **Acceptance**：One ruling: either wire set_pacing_floor(expected_rows) from the enumeration entry point keeping None as the conservative default, or delete the seam and its docstring claim; boundary tests cover N=1 and N=2.
- **Registered**：2026-10-02T14:54:03.223Z
- **Revision**：1

### I-000179 [low] (bug)

**AUDIT-2026-10-02R2: cli/run.py still spells the terminal status set inline in both scope predicates while TERMINAL_STATUSES has five other importers**

- **Impact**：run.py:49 and :66 spell {"archived","gone"} inside the pending/failed scope filters; manifest.TERMINAL_STATUSES is the same fact imported by coverage_report, scheduler, coordinator and campaign. A third terminal status would be honoured by every other reader and ignored by run's scopes, silently re-queuing terminal rows; no test pins either literal.
- **Acceptance**：Both run.py predicates use TERMINAL_STATUSES, and a test pins the two forms equal so a future third status cannot diverge.
- **Registered**：2026-10-02T14:55:02.485Z
- **Revision**：1

### I-000180 [low] (improvement)

**AUDIT-2026-10-02R2: services/_common.py's 'single injectable clock' is bypassed five times in queue_source.py, and plan 010's dead-import cleanup left two unused imports in cli/meta.py**

- **Impact**：_common._now() is documented as the one home for the run/attempt clock, but queue_source.py calls the wall clock at :293/:316/:373/:436 plus a function-local `import time as _time` shadow at :134, and no test patches the clock — so persisted timelines are not pinnable. Separately, cli/meta.py:13/:20 still import _format_run_line and _run_error_codes whose bodies plan-010 deleted; with no linter configured nothing catches it.
- **Acceptance**：queue_source uses the shared clock (or the shadow and extra call sites are removed with a reason), and the two unused imports are dropped; a lint rule or a pin prevents recurrence.
- **Registered**：2026-10-02T14:55:03.033Z
- **Revision**：1

### I-000183 [low] (bug)

**E2E-2026-10-03: a bvid-scoped asr invocation records selector_kind=pending with selector_target NULL, claiming a whole-queue scope**

- **Impact**：The ASR run ledger cannot answer which work a run was scoped to: a single-part invocation (asr --bvid BV1aAhLzsENb:p0) is indistinguishable from an unbounded queue run. Operator-facing run review and any future resume-by-run logic are misled, and the schema CHECK that pairs a bvid selector with a target is defeated by always writing pending.
- **Acceptance**：A bvid-scoped asr invocation records selector_kind=bvid with selector_target set to the requested work id; a queue-scoped invocation keeps selector_kind=pending with a NULL target; a regression test pins both.
- **Registered**：2026-10-02T23:36:17.186Z
- **Revision**：1

### I-000184 [low] (bug)

**E2E-2026-10-03: the default asr path stores language='und' for a Chinese transcript, so every ASR row is de-identified**

- **Impact**：The transcripts row for a Chinese-language ASR run carries language='und' because the write-back falls back when provenance carries no language. Every default-path ASR row is therefore unlabelled for language, which weakens reader filtering (search --language), makes the uniqueness key (video_part_id, source_kind, language, version) coarser than intended, and contradicts the plan/design wording that the value comes from provenance.
- **Acceptance**：An ASR write-back records the transcript's actual language (or a deliberate, documented constant if the engine genuinely does not expose one); a regression test pins the value for a known-language part and the fallback is named in the contract.
- **Registered**：2026-10-02T23:36:26.904Z
- **Revision**：1

### I-000185 [low] (bug)

**E2E-2026-10-03: coverage/verify exit non-zero on a healthy archive because the plain CLI writes no evidence sidecars**

- **Impact**：On a freshly built archive produced only through the documented CLI path, the two reader commands an operator would use to judge health both exit 1: coverage --strict reports cumulative complete 1/1 while listing four evidence_missing diagnostics (attempts, cursor, run_ledger, scheduler), and verify reports defect_count 0 / backlog_count 0 with two structural_input_error diagnostics. The exit code therefore cannot be read as 'something is wrong' — it fires on a completely successful run, which trains the operator to ignore it.
- **Acceptance**：Either the CLI paths emit the evidence the readers expect, or the readers distinguish 'no evidence was recorded by this path' from 'evidence is missing/corrupt' so a healthy archive exits 0; a test pins the exit code for an archive built only through asr/download-audio/harvest-subs.
- **Registered**：2026-10-02T23:36:36.639Z
- **Revision**：1

### I-000191 [low] (bug)

**Two coordinator docstrings still assert the caption write-back runs before the `archive: ok` record, which plan caption-writeback-guard's call-site move made false**

- **Impact**：`coordinator.py:735-738` and `coordinator.py:1373-1379` both claim the write-back ordering to the attempt ledger (the `:735` one adds a mechanism claim, 'the row count the summary reads', that no reader implements). L2 review verified all `attempts.jsonl` consumers and the summary: `fully_processed` counts `RowResult`, never transcript rows, so nothing requires the old order — the move is legitimate and the sentences are simply wrong. Docstrings are the only description of the R14 write-back contract at those two sites, so a later reader trusting them will re-derive a constraint that does not exist.
- **Acceptance**：Both sentences are corrected to state the actual contract: the write-back is best-effort and runs after `_mark_archived`, outside the archive success guard; its outcome never rewrites the row's archived outcome. Verified when: neither docstring claims a pre-`archive: ok` ordering or an attempt-ledger row-count reader, and `grep -n 'before the attempt ledger records' coordinator.py` is empty.
- **Registered**：2026-10-03T03:00:10.702Z
- **Revision**：1

### I-000192 [low] (improvement)

**The caption write-back has no swallow boundary at its call site, so a store failure leaves the operator seeing exit 1 on a durably-archived row**

- **Impact**：After plan caption-writeback-guard, the row's durable outcome is correct (published bundle is recorded `archived`, ledger `archive: ok`), but `_record_subtitle_transcript` still converts only the argument-time shapes it validates; a non-ValueError store failure propagates out of the call site, leaving `result.ok = False` / `final_status = subtitle_done` and CLI `exit 1` even though the archive landed. The ASR sibling instead converts inside its own try, so the two paths still differ in exactly this respect. Blast radius is bounded and correct-by-design for durability; what is missing is the operator-facing success signal.
- **Acceptance**：Convert the store-write-back failure at the call site the same way the ASR sibling does (a local try whose except records the skip and returns), so a store outage cannot turn a durably-archived row into a non-zero exit; keep the archived outcome and the `archive: ok` ledger record unchanged. Verified when: a test drives the caption archive path with an injected store failure and asserts CLI success plus the archived row, and the caption tail again mirrors `_stage_asr_archive`'s shape.
- **Registered**：2026-10-03T03:00:11.261Z
- **Revision**：1

### I-000196 [low] (bug)

**Manifest journal decode policy is asymmetric across the three readers: _replay_latest substitutes invalid UTF-8 (errors="replace") and the rewritten snapshot then persists the substituted key**

- **Impact**：`manifest.py:260` decodes with `errors="replace"` while its two sibling readers of the same journal are strict: the sidecar projection decodes strictly and reports `invalid_utf8` (`sidecar_projection.py:131`, `:135-136`), and `AttemptLedger._replay_tail` decodes strictly with the rule documented at `coordinator.py:315-316` ('a mutilated record cannot pass as valid through U+FFFD') and pinned by `test_invalid_bytes_in_tail_fail_closed`. Because the manifest side substitutes, a mutated byte inside `work_id` becomes a different but VALID key: QC seat 1 probed a lone 0xFF in `work_id` loading as `'BV1\ufffd:p0'`, and a following `save()` durably writes `{"work_id":"BV1\uFFFD:p0",...}` into the snapshot and unlinks the journal — i.e. the reader that WRITES rewrites corruption into the durable record, while the readers that only REPORT are strict. No in-repo writer can produce the input (a single `O_APPEND` site at `manifest.py:278` writing `_json_line` output), so only a foreign writer, an external edit or media corruption reaches it. Kept low rather than high because strict decode is itself a policy choice with its own risk (one bad byte would fail `load()` on a resumable SSOT) — the defect is the asymmetry and the missing decision, not either policy.
- **Acceptance**：The manifest journal's decode policy is decided in one place and stated where the split rule is stated: either strict (matching `AttemptLedger` and its pinning test) or substitute-but-never-rewrite-the-substituted-key. Verified when: a journal row containing a lone 0xFF in `work_id` either fails `load()` fail-closed, or loads with the substitution recorded and does NOT get written back into the snapshot by a subsequent `save()`; plus a test pinning whichever policy is chosen.
- **Registered**：2026-10-03T06:54:37.585Z
- **Revision**：1

### I-000197 [low] (improvement)

**The ASR run-refusal diagnostic's per-instance latch equals per-invocation only because all three run_batch callers are single-batch today, and that invariant is stated nowhere**

- **Impact**：Plan asr-run-id-uniqueness's D8 decision rules that a refused acquisition run prints at most one stderr line per `QueueSource` instance, reasoning from a persistently-refusing store. Two plan-QC seats reached this from different directions: seat 3 read the coordinator's per-batch re-open (`coordinator.py:689-706`, `:1196-1211`) and reported N batches ⇒ N lines; seat 1's caller census refined that to **latent, not live** — `run_batch` has exactly three `src/` call sites (`cli/run.py:334`, `:556`, `campaign.py:335`), each single-shot with no loop, and `pilot` reuses one source across its whole `--n` loop (`cli/pilot.py:584-611`), which is the per-invocation scope. So the equality the latch rests on holds only because of an unstated property of today's callers: a future caller that loops batches over one invocation reproduces exactly the per-call noise floor D8 names, and the adjacent `_writeback_source_failed` latch (`coordinator.py:691`/`:699`) is deliberately coarser (it survives batch boundaries), so the two latches have different scopes with nothing documenting why.
- **Acceptance**：The scope of the refusal latch is either stated where it is specified (an explicit 'one invocation = one batch = one source' note at the latch and in the coordinator's per-batch re-open), or hoisted to the coordinator so its scope matches the invocation regardless of caller shape. Verified when: a reader of `_report_refused_asr_run` can tell from the code which scope the latch covers and why it differs from `_writeback_source_failed`'s, and a looping caller would not silently produce per-batch repeats.
- **Registered**：2026-10-03T09:49:30.714Z
- **Revision**：1

### I-000198 [low] (bug)

**Narrowing ensure_asr_run's except drops TypeError, so a connection-contract violation escapes the write-back and is reframed as a per-row archive failure after `archive: ok` was already written**

- **Impact**：Plan asr-run-id-uniqueness narrowed `QueueSource.ensure_asr_run`'s `except` from bare `Exception` to `(sqlite3.Error, OSError, ValueError)` — correct per its brief, but `MediaQueueRepository._validate_connection` raises **`TypeError`** (`storage/database.py:231`: 'connection must use the sqlite3.Row row_factory'), and that class is no longer caught. A connection whose contract is violated *after* construction therefore escapes the write-back call site instead of degrading to the documented `asr_run_id = None` skip: on the coordinator path the stage's `except Exception` (`coordinator.py:855-860`) records `archive: failed` and re-raises for a row whose `archive: ok` attempt evidence was already written and whose bundle is complete on disk; at `cli/asr.py:151` nothing encloses the call (that module has only a `finally`) so the invocation ends in an uncaught traceback instead of the diagnostic. Reachability is a prerequisite-violation shape, not a daily path: `QueueSource.__init__` (`:114`) already runs the same validation via `MediaQueueRepository`, so the trigger needs a connection contract lost after construction — which is why both the finding seat and the architecture seat graded it non-blocking. It is filed separately from `I-000192` because that issue is the *caption* call site's missing swallow boundary; this one is the *narrowed tuple's* consequence and its fix belongs at whichever boundary the iteration decides for `I-000192`.
- **Acceptance**：A connection-strategy violation inside the write-back no longer turns a durably-archived row into a failed-row record or an uncaught traceback. Either the tuple covers the classes the call path can actually raise (matching the module's sibling handlers, which already name `(_sqlite3.Error, OSError, ValueError, TypeError, KeyError)` at `queue_source.py:446`/`:508`), or the call boundary converts it (`I-000192`). Verified when: a test drives the write-back with a connection whose `row_factory` was reassigned and asserts the row keeps its `archive: ok` outcome with a diagnostic rather than a failure record, or the narrowed tuple is shown to be unreachable for that shape by construction.
- **Registered**：2026-10-03T09:50:10.962Z
- **Revision**：2

### I-000199 [low] (bug)

**The D8 refusal diagnostic changes the process exit code to 120 when stderr dies mid-flight: the swallowed failed write still dirties the interpreter's stderr buffer, whose shutdown flush raises**

- **Impact**：Plan asr-run-id-uniqueness added an instance-latched refusal line printed to stderr (D8). When fd 2 dies **after** startup, `sys.stderr` remains a live `TextIOWrapper`; the write fails, the widened guard (`print` wrapped in `except (OSError, ValueError, TypeError)`, added by commit `a23b44c`) swallows it, `ensure_asr_run` returns `None` and nothing raises through it — but the failed write leaves the interpreter's stderr buffer dirty, and CPython's **shutdown** flush retries it and raises, so the **process exits 120** instead of 0. This is a behaviour change introduced by this iteration (`d67f84c`), not a base defect: the plan-QC revalidation's `exit 120` note about the *method* escaping was closed by the guard, and the QA gate then isolated the residual at a different seam. Control measurements: `os.close(2)` alone → exit 0; `os.close(2)` + a swallowed failed stderr print → exit 120; `os._exit(0)` right after the library call → exit 0 (proving the 120 is the shutdown flush, not an escaping exception). Reachability is nil in-product: no `src/` code closes or replaces fd 2 (no `dup2`, no `detach()`, no daemonization), so this needs an out-of-tree host, a supervisor, or a shell whose `stderr` reader exits early (same result measured for `2> >(head -c 0)`). The reason it is still worth capturing rather than waiving: the same print-to-stderr shape exists at two precedent sites (`coordinator.py:1260`, `asr.py:102`) that were not probed, and an exit-code change is observable to any caller checking `$?` — a scope broader than the diagnostic itself.
- **Acceptance**：Either the plan-level contract accepts that a diagnostic may change the exit status of a process whose stderr died mid-flight, or the diagnostic's write path avoids dirtying a buffer whose flush can raise at shutdown. Verified when: for each print-to-stderr diagnostic site (`queue_source._report_refused_asr_run`, `coordinator._print_model_constructions`, `asr.py:102`), a probe with fd 2 closed mid-process reports the process exit code, and the outcome is either documented as accepted or the sites share a write path that does not alter it.
- **Registered**：2026-10-03T11:08:48.156Z
- **Revision**：1

### I-000202 [low] (improvement)

**ManifestStore._journal_bytes is write-only state after the compaction trigger became file-based, and save()'s empty path zeroes it while a torn journal may still be on disk**

- **Impact**：Plan journal-compaction-lifecycle's Task 1 made the compaction trigger a function of the file sizes on disk (both `os.path.getsize`), which removed the last **reader** of `self._journal_bytes`. At HEAD it is assigned in 14 places (`manifest.py:131, 220, 226, 300, 327, 396, 402, 407, 415, 419, 450, 474, 550, 609`) and never read as a value — the only occurrence that consumes it is its own `+=` at `:300`. The plan's Task 1 brief explicitly requires keeping it ('it is the on-disk byte carrier `_replay_latest` returns and `load()`/`upsert()`/`migrate_legacy_rows()` maintain'), so keeping it is spec-compliant and it is not a defect of this plan; but the plan-owner instruction and the code's actual use have diverged, leaving state that a future reader may mistake for a live input. The L2 review's second half: `save()`'s empty-`current` early return sets `self._journal_bytes = 0` while a torn trailing journal line may still be on disk — harmless today precisely because nothing reads it, and a trap if a future change starts reading it. Either delete the member with the parameter it belonged to, or give it a reader and say what the zero means on the empty path.
- **Acceptance**：`self._journal_bytes` is either removed (with every assignment and the `_replay_latest` return tuple's second element, if it becomes unused) or documented with a stated reader and a defined meaning on `save()`'s empty-`current` path. Verified when: a reader can tell from the code which of the two it is, and no branch assigns a value that contradicts what the file on disk holds without a comment saying so.
- **Registered**：2026-10-03T12:13:59.684Z
- **Revision**：1

### I-000203 [low] (risk)

**save() publishes the snapshot before discarding the journal, so a crash in that window leaves a stale journal a later journal-wins replay would re-publish**

- **Impact**：Plan journal-compaction-lifecycle's Task 2 deliberately reordered `save()` to `_replace_snapshot(current)` then `_remove_journal()` — the correct order for the failure that matters (`I-000138`: never discard a journal whose rows were not folded, since a crash between an unlink and the replace loses every journal-only row). The L2 review records the mirror-image window this order creates: a crash **after** the successful `_replace_snapshot` and **before** `_remove_journal` leaves the previous journal on disk beside the new snapshot, and the next journal-wins replay re-publishes those older rows over the newer snapshot. Reachability today is nil: `save()` has zero `src/` callers, and the re-publish needs the caller-supplied `save(entries)` form whose entries the journal then overwrites. It is filed because the two orders trade one hazard for the other and the plan should not leave that asymmetry implicit — the discard is only safe once the publish is durable, which is what the order relies on and what a future reader should see stated.
- **Acceptance**：The `save()` window is either closed or explicitly accepted with its precondition written down. Verified when: either the discard is made conditional on the published snapshot having been observed durable (or is made idempotent against a re-publish), or `save()`'s docstring states that a crash between the publish and the discard can re-publish journal rows over the snapshot, together with the precondition that keeps that harmless today (no `src/` caller uses the `save(entries)` form).
- **Registered**：2026-10-03T12:14:10.330Z
- **Revision**：1

### I-000208 [low] (improvement)

**The iteration's integration branch survives Phase 6 cleanup: squash merge breaks ancestry, so the cleanup guard refuses and the branch is left as a residual**

- **Impact**：Phase 6 §6.4 cleanup removed this iteration's four worktrees and its three fix branches, and then correctly refused the integration branch: `iteration/iter-2026-10-ledger-integrity` (local tip `ec9d3d2`) is not an ancestor of `origin/main`, because PR #35 was squash-merged into the single commit `1de04c5`. The cleanup guard proves a merge by ancestry, so it reports `cleanup.refuse.unmerged` for both the local and the remote ref, and the owning contract's rule for this shape is explicit: STOP and leave a residual rather than force-delete (`git branch -D` is forbidden here, and the engine refuses the remote path too). The merge itself is verified independently — PR #35 is `MERGED` with merge commit `1de04c51d148a58936d196c667b14beeaf027366` on `origin/main`, and the control root's `main` carries an identical product tree (`git diff --stat origin/main..main -- bilibili-asr-archive/` is empty) — so this is a bookkeeping residual, not an unmerged-work risk. It is worth recording because both refs keep pointing at a commit whose work is already on `main`, and because the repo's own convention is that merged iteration branches do not linger (the three previous iteration branches are absent from the remote).
- **Acceptance**：Either the two refs are removed with the squash merge recorded as their merge evidence, or the residual is explicitly accepted as permanent. Verified when: `git ls-remote --heads origin iteration/iter-2026-10-ledger-integrity` is empty and the local branch is gone, and the removal cites PR #35's merge commit — or the decision to keep them is stated in the iteration package so a later reader does not re-litigate it. Note the guard itself should not be bypassed by hand: if the ancestry rule is wrong for squash-merge repos, the repair belongs in the cleanup guard's evidence consult, not in a one-off `git push --delete`.
- **Registered**：2026-10-03T15:59:44.296Z
- **Revision**：1

### I-000211 [low] (bug)

**probe-subs leaves no durable trace while harvest-subs writes the caption verdict, so the two commands can still describe one part differently with nothing on disk to reconcile them**

- **Impact**：Plan caption-exhaustion-attestation Task 2 required that probe-subs and harvest-subs not contradict each other on the same input without leaving a trace. The harmful half is closed: under the corroboration rule a single harvest observation no longer admits a part to the paid branch, so the measured I-000187 sequence (probe reports tracks=0, harvest stores subtitle-ai minutes later) can no longer route a captioned part into ASR. What remains is the asymmetry itself: SubtitleIngestor.probe is read-only by its own docstring ('List what each selected part exposes, writing nothing at all', services/subtitle_ingest.py:317-321) and records no attempt row, while harvest records one. An operator who probes, sees 'no subtitles visible', and acts on it takes an action no durable record explains.
- **Acceptance**：Decide whether probe-subs should record its observation. Recording would require opening an acquisition_run (attempt rows carry an FK to it) and would turn a read-only command into a mutating one, changing its contract and its use on a read-only archive; that is why it is not done here. If it is decided against, this residual should be closed as a recorded decision rather than left open. If it is decided for, note that a probe-observed empty inventory would then count toward corroboration, which interacts with I-000210 (credential-absent runs) and would make the counter reachable without a harvest at all.
- **Registered**：2026-10-03T20:28:13.243Z
- **Revision**：1

## Resolved / Waived（共 36 条）

| ID | Severity | Kind | Title | Closed at |
|---|---|---|---|---|
| I-000001 | low | review-obligation | Adapter binds the whole `user` module, so `user.get_api` reaches every endpoint  | 2026-09-17 |
| I-000002 | low | review-obligation | The model-load attempt count is recorded but printed nowhere an operator can see | 2026-09-17 |
| I-000003 | low | review-obligation | Model-load retries stay unbounded per row (a failed load is retried once per row | 2026-09-17 |
| I-000004 | low | review-obligation | A *failed* model load is retried once per row (`factory_attempts == N` for an N- | 2026-09-17 |
| I-000005 | low | review-obligation | The per-batch reuse count lives only on stderr: it is not in `CampaignSummary.to | 2026-09-17 |
| I-000006 | low | review-obligation | `guides/hygiene-report.md:15,30` publishes a bare `python3.12 scripts/check_asr_ | 2026-09-17 |
| I-000007 | low | review-obligation | The six Latin-script hotwords added 2026-09-14 are unverified: their shards are  | 2026-09-17 |
| I-000008 | medium | review-obligation | `scripts/verify_baseline.py`'s staged tree cannot collect `tests/test_check_asr_ | 2026-09-17 |
| I-000009 | low | review-obligation | The iteration compass's A1 row still tells QA to run `python3.12 scripts/check_a | 2026-09-17 |
| I-000010 | low | review-obligation | The retirement map's `asr_low_confidence_at` row (where the doubt is) has no liv | 2026-09-17 |
| I-000011 | low | review-obligation | The repeated-ngram pass is O(joined text), bounded only by the artifact byte cap | 2026-09-17 |
| I-000012 | low | review-obligation | The full local suite is intermittently red for no product reason: ~200-260 tests | 2026-09-18 |
| I-000018 | low | review-obligation | The implementer's Task 2 report still shows `14:30:xx` / `14:51:xx` in its run t | 2026-09-18 |
| I-000022 | medium | review-obligation | The projection **replaces** the manifest row it marks `archived` instead of merg | 2026-09-20 |
| I-000027 | low | review-obligation | The command's `--help` says it writes "only below the artifact root and to the m | 2026-09-20 |
| I-000031 | high | review-obligation | **The ASR hotword list is also an insertion source.** A token from the run's own | 2026-09-27 |
| I-000037 | high | review-obligation | **The merged ASR boundary could not read the audio the archive's own downloader  | 2026-09-27 |
| I-000038 | high | review-obligation | **The Qwen3 rewrite silently rewrote the hotword list.** Commit `2548ca9` delete | 2026-09-27 |
| I-000047 | medium | review-obligation | The Task 2 L2 review seat DIED with no verdict: the reviewer wrote a 330-byte sk | 2026-09-28 |
| I-000048 | high | review-obligation | A-R4 CLOSED AS FULFILLED, AND IT EARNED ITS KEEP: the fresh L2 review over 9b253 | 2026-09-28 |
| I-000049 | medium | review-obligation | The Phase 3 close commit `3a5b638` and the compass frontmatter `status: complete | 2026-09-28 |
| I-000063 | high | review-obligation | P1: the cli.py split (`7a26158`) left 12 unresolved names across THREE cli modul | 2026-10-01 |
| I-000064 | medium | review-obligation | Second defect behind the same test gate: several suites call `main(["schedule",  | 2026-10-01 |
| I-000065 | medium | review-obligation | The store queue route cannot select a part whose caption is already in hand: `en | 2026-10-01 |
| I-000074 | medium | review-obligation | A multi-line upstream `description` would raise `GatewayShapeError` from `_text` | 2026-09-30 |
| I-000075 | low | review-obligation | Task 4's L2 review slot is OWED: the dispatched reviewer wrote `task-4-review.md | 2026-09-28 |
| I-000088 | low | review-obligation | WITHDRAWN by its author: the two-base `any()`-over-bases masking hole did not re | 2026-09-27 |
| I-000094 | high | review-obligation | NO LIVE-CORPUS VERIFICATION. Layout shape A moved every published artifact to tr | 2026-09-28 |
| I-000107 | low | review-obligation | `check-asr-env` anchors its helper script at the wrong root, so the README-publi | 2026-09-20 |
| I-000113 | high | review-obligation | Two public readers treat a normally-produced manifest as malformed: `verify` can | 2026-09-18 |
| I-000114 | low | review-obligation | The six Chinese homophone hotwords added 2026-09-17 (扬弃 自在 变易 此在 感性 实存) are unve | 2026-09-18 |
| I-000115 | low | review-obligation | `pilot` writes no stage-attempt records, so `--scope failed` cannot see a row th | 2026-09-18 |
| I-000116 | low | review-obligation | An externally killed `run` leaves no `run-ledger.jsonl` record: the record is ap | 2026-09-18 |
| I-000134 | high | review-obligation | **The `.m4a` codec fallback is inert under the `librosa` the project's own decla | 2026-09-27 |
| I-000204 | critical | bug | The file-based compaction trigger folds by whole-file journal size while the rep | 2026-10-03T14:51:52.938Z |
| I-000205 | high | bug | A torn journal fragment has no repair path: every row appended after it is perma | 2026-10-03T14:52:17.736Z |
