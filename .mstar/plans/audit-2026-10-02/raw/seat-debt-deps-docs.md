# Seat findings — t4 [T4-debt-deps-docs]: tech-debt/architecture + dependencies/migrations + docs

Scope: delta `ff39fd0..1e756df` of `bilibili-asr-archive` (read-only), plus the open issue register as
context. Playbook read: `mstar-audit/references/audit-playbook.md` (§5 Tech Debt & Architecture incl.
Prove-or-reject, §6 Dependencies & Migrations, §8 Docs, Finding format).
Landed plans 001–010 and already-registered rows are cited, never re-reported.

---

### [DOCS-01] `manifest.journal.jsonl` is a new durable artifact the operator contract never names

- **Evidence**: `bilibili-asr-archive/src/bili_asr/manifest.py:48` (`JOURNAL_NAME = "manifest.journal.jsonl"`,
  new in this delta) and `:122` (`self._journal_path`); appends land in the journal and the snapshot is
  only rewritten on compaction (`manifest.py:409-419` upsert docstring, `_maybe_compact_locked:294-316`,
  thresholds `:53-56`). `grep -rn 'manifest.journal|journal.jsonl' README.md docs/*.md` → **no match**;
  README still states the older single-file model at `README.md:1000` ("The JSONL manifest
  (`{archive-root}/manifest/manifest.jsonl`) remains the single source of truth (SSOT)") and its
  archive-root inventory `README.md:566-570` lists what stays at the root without the journal. The
  rationale exists only in harness knowledge: `.mstar/knowledge/architecture-patterns/journal-ledger-and-projection-replay.md:18`.
- **Impact**: between compactions the newest rows of the resumable SSOT are only in the journal, so any
  operator action derived from the README sentence — copying `manifest.jsonl` to a new root, diffing it,
  inspecting it to answer "why is this part not archived" — silently reads a stale projection. This is
  the same class as the registered `I-000033` (versioned register pointing at unversioned documents):
  a durable artifact exists but is absent from the contract that tells people what to back up.
- **Effort**: XS — one paragraph in the manifest/SSOT section plus the `manifest/` inventory line.
- **Risk**: LOW — documentation only; no code, no behavior.
- **Confidence**: HIGH — the file name and its write path are in the delta and no README/docs sentence
  mentions it.
- **Fix sketch**: state the two-file model where the SSOT is currently asserted (snapshot + journal,
  journal folded in on compaction), and list `manifest/manifest.journal.jsonl` next to `manifest/` in the
  archive-root inventory; point at the knowledge doc for the invariant.

---

### [DEBT-01] The "single injectable clock" for the service layer has two of three siblings bypassing it

- **Evidence**: `bilibili-asr-archive/src/bili_asr/services/_common.py:1-16` — module docstring claims
  "Single home for the run/attempt Unix-second clock the ingest services persist; injectable so tests
  can pin the persisted timeline", with consumers only `services/metadata_ingest.py:28` and
  `services/subtitle_ingest.py:40`. Its sibling `services/queue_source.py` calls the wall clock directly
  five times (`:293`, `:316`, `:373`, `:436` bare `time.time()`, plus `:141` via a function-local
  `import time as _time` shadow of the module-level import at `:22`). No test patches the queue clock:
  `grep -rn 'queue_source.time' tests/` → no match.
- **Impact**: the injectable-clock property plan 010 cluster 4 introduced is one-third true. Two
  consequences that are not stylistic: (a) a test that needs a deterministic persisted timeline for the
  queue/acquisition path cannot get one, so the attempt-ledger and audio-acquisition rows keep being
  asserted through whatever the machine clock happens to say; (b) the module docstring states a
  guarantee that is false as written, which is the failure mode the repo's own
  `best-practices/claim-scope-discipline.md` names. The local re-import at `:134` also signals the
  original consolidation never reached this file.
- **Effort**: XS — import `_now` and replace five call sites (plus delete the function-local import).
- **Risk**: LOW — same integer-second semantics; the only behavior change is under an injected clock.
- **Confidence**: HIGH — the five call sites and the two consumers are read directly.
- **Fix sketch**: point `queue_source.py` at `services/_common._now`; either generalize the docstring to
  name it as the service-layer clock for all three modules, or keep `_common` and make it the only
  import site so the claim becomes true.

---

### [DEBT-02] The terminal-status set is centralised but `cli/run.py` still spells the literal twice

- **Evidence**: canonical home `bilibili-asr-archive/src/bili_asr/manifest.py:40`
  (`TERMINAL_STATUSES = frozenset({"archived", "gone"})`), consumed by `coverage_report.py:412`,
  `scheduler.py:112`, `coordinator.py:1057/1146/1275`, `campaign.py:338`. `cli/run.py:49`
  (`if e.get("status") in VALID_STATUSES - {"archived", "gone"}`) and `cli/run.py:66`
  (`and e.get("status") not in {"archived", "gone"}`) still carry the literal, in the one module that
  decides what `--scope pending` and `--scope failed` will process. No test pins the constant:
  `grep -rn TERMINAL_STATUSES tests/` → no match.
- **Impact**: this is a live drift axis, not a style point. Adding a third terminal status updates the
  five importers and leaves both `run.py` branches behind, so `run --scope pending` starts feeding
  terminal rows back into the stage pipeline while the scheduler and coverage report consider them
  finished. Pairwise guards exist elsewhere for the in-flight set (`I-000091`), but nothing guards this
  one, and the two literals sit in different branches of the same function.
- **Effort**: XS — two substitutions plus a one-line equality assertion in the existing manifest tests.
- **Risk**: LOW — `VALID_STATUSES - {"archived","gone"}` is exactly `VALID_STATUSES - TERMINAL_STATUSES`
  today, so the substitution is behavior-preserving.
- **Confidence**: HIGH.
- **Fix sketch**: import `TERMINAL_STATUSES` alongside `VALID_STATUSES` in both `run.py` scope branches;
  add a test asserting the run-scope pending predicate equals `VALID_STATUSES - TERMINAL_STATUSES` so
  the next status addition fails loudly instead of silently re-queueing terminal rows.

---

### [DOCS-02] README's manifest append-cost model describes the pre-journal implementation

- **Evidence**: `bilibili-asr-archive/README.md:1309-1312` — "each appended row is one locked re-read of
  the whole ledger plus two `fsync` calls … appending `N` rows to an `L`-line ledger costs about
  `N·L + N(N−1)/2` line parses — at `N = L = 2,000` roughly 6M parses and 4,000 fsyncs." The delta's
  implementation contradicts the per-row re-read: `manifest.py:409-419` ("Persistence is an O(1) journal
  append: the full snapshot re-read now happens only once, on the first upsert of a store instance"),
  `_append_record:266-294` (one `os.write` + one file fsync + one directory fsync, no read),
  replay driven by `_journal_stat_signature` only when another process moved the journal
  (`manifest.py:201-220`).
- **Impact**: the README keeps the number as the *only* guidance for a first full-queue derivation
  ("no runtime measurement was taken on a real archive"), so an operator sizing a 2,000-row derivation
  is told to expect a 6M-parse, 4,000-fsync hold on the writer lock when the code now performs one
  replay plus a bounded append per row. The same stale premise is what register row `I-000028`
  (O(N²) `ManifestStore.upsert`, cited at `manifest.py:280`) rests on — closing or re-scoping that row
  and fixing this paragraph are the same edit.
- **Effort**: XS — rewrite the bullet with the post-journal complexity and say what is still unmeasured.
- **Risk**: LOW — documentation only.
- **Confidence**: HIGH — both the README sentence and the upsert docstring are read directly.
- **Fix sketch**: replace with "one replay at store construction + one append (one write, two fsyncs) per
  row; the `N·L` term applies only to the first `load()` per process and to a foreign-writer replay";
  keep the honest "analytic, not measured" caveat and state which term is now bounded.

---

### [DOCS-03] `docs/metadata-storage.md` still declares the ASR/audio store tables empty after the delta wired their writers

- **Evidence**: `bilibili-asr-archive/docs/metadata-storage.md:72-77` — "`audio_objects`,
  `part_audio_objects`, and `asr_models` are still empty: no audio bytes and no ASR model rows are
  written by any command here. The legacy audio/ASR chain (`download-audio`, `asr`, `pilot`, `run`)
  still records its work in the JSONL manifest, not in these tables." The code contradicts both
  halves: `storage/database.py:1198` inserts into `asr_models` from
  `TranscriptRepository.record_local_transcript` (`:1139`), `:1816` inserts into `audio_objects` and
  `:1862` into `part_audio_objects` from `MediaQueueRepository.mark_audio_acquired` (`:1731`); the
  callers are shipping CLI/coordinator paths — `cli/asr.py:290`, `cli/pilot.py:601`,
  `coordinator.py:794` (`record_local_transcript`) and `cli/queue.py:193/397`, `cli/pilot.py:364`
  (`mark_audio_acquired`). The delta introduced both wirings (`11374d1 feat(asr): write local ASR
  transcripts back to the store (R14)`, `aee6f2e`), while
  `git log --name-only ff39fd0..1e756df -- docs README.md` is **empty** — the code moved and the doc did not.
- **Impact**: this file is the published boundary document (`I-000112` names it as the boundary the ASR
  chain deliberately crosses only through the manifest), so an operator or the next audit reading
  "these tables cannot fill; nothing on this path writes them" will re-derive a pre-R14 model of the
  store's completeness and discount rows that the delta now writes. Register row `I-000105`
  ("ASR work never reaches the store") carries the same pre-R14 premise.
- **Effort**: XS — update the paragraph to name the two writers and their CLI entry points.
- **Risk**: LOW — documentation only.
- **Confidence**: HIGH for the doc being wrong; the writer methods and their call sites are read
  (not executed — the read-only mandate forbids a live run, so the exact row counts a real run produces
  are not evidenced here).
- **Fix sketch**: replace the paragraph with the post-R14 statement (caption path via
  `record_acquired_transcript`, local ASR via `record_local_transcript`, audio via
  `mark_audio_acquired`), and note the chain's remaining manifest-only surface rather than claiming the
  tables are unwritten.

---

### [DEBT-03] Plan 010's dead-code deletion left two unused imports in `cli/meta.py`

- **Evidence**: `bilibili-asr-archive/src/bili_asr/cli/meta.py:13` and `:20` import `_format_run_line`
  and `_run_error_codes` from `bili_asr.cli._shared`; the file never references either name again
  (grep over the module returns only those two definition/import lines; the definitions live at
  `cli/_shared.py:431` and `:448`, real consumers are `cli/status_cmd.py:484/488`). Commit
  `68b6bcc refactor(cli/meta): delete dead _run_error_codes/_format_run_line/_resolve_sessdata shadows
  (plan 010 cluster 3)` removed the bodies but not the imports.
- **Impact**: no runtime effect, but this is the residue the prior audit's "nothing left to dedupe"
  claim did not cover, and it misleads exactly the way `I-000090` describes (a stale artifact that
  implies a capability the module does not have): a reader scanning imports concludes `fetch-meta`
  prints run-error lines. There is no linter or CI workflow in the tree to catch it
  (`.github/workflows` absent; no ruff/flake8 config), so it will not surface on its own.
- **Effort**: XS — delete two import lines.
- **Risk**: LOW — verified unused; `cli/meta.py` is still live (`cli/__init__.py:33` imports its three
  handlers), so the check is "unused import", not "dead module".
- **Confidence**: HIGH.
- **Fix sketch**: drop the two names from the `_shared` import list; if the repo wants this class of
  residue to be self-detecting, add the F401/F821 linter pass as its own small plan rather than
  hand-checking each dedup cluster.

---

### [DEP-01] One upstream, two HTTP stacks: the requests-based client carries application-level WAF machinery the curl_cffi-backed pin does not need

- **Evidence**: `bilibili-asr-archive/src/bili_asr/bili_client.py:172` (`class RequestsTransport`,
  `import requests` lazily at `:174`), `:208` (`build_default_transport()`), used as the default in
  `BiliClient.__init__:232` and constructed by shipping commands — `cli/run.py:108/320/513`,
  `cli/pilot.py:503`, `cli/queue.py:299`. In parallel the pinned library path runs on curl_cffi:
  `pyproject.toml:12-14` (`requests>=2.32`, `bilibili-api-python==17.4.2`, `curl_cffi>=0.16`),
  README `:1096-1102` ("the pinned distribution declares no HTTP client of its own, so `curl_cffi` is a
  declared runtime dependency"), and the installed pin imports it itself
  (`bilibili_api/clients/CurlCFFIClient.py:15`). The hand-rolled stack pays for the difference in
  application code: `classify_risk` (`bili_client.py:85`), `RiskBudgetExhausted` (`:128`),
  `_wbi_keys`/`get_mixin_key`/`sign_wbi` (`:390`, `:47`, `:53`).
- **Impact**: the same host is reached two ways with two TLS/UA postures (browser impersonation through
  curl_cffi on the metadata path; plain `requests` with hand-set headers + a bespoke risk budget and
  WBI signer on the subtitle/audio path). Cost is paid three times: two error/risk vocabularies to keep
  consistent, two places to change when the upstream hardens (the delta already had to grow the gateway
  during this window), and the `requests` declaration exists only to feed the non-impersonating stack.
  Read honestly: this is *not* proof the library covers the audio-download surface the hand-rolled
  client serves, and the swap bar in the playbook requires exactly that. What is evidenced is the
  duplication, not that the library is a drop-in.
- **Effort**: L — audit each `BiliClient` endpoint against the library's coverage (subtitle list,
  playurl/dash, streaming download), then retire `RequestsTransport` + the WBI/risk machinery only for
  the endpoints that are covered; a partial retirement is not worth it.
- **Risk**: MED — the hand-rolled path is the one exercised by the archive's own live smokes; a
  mis-scoped swap would regress subtitle harvesting, which is the product's first-choice source.
- **Confidence**: MED — duplication and reachability are HIGH-confidence (read directly); the
  library-coverage half is unverified in this pass.
- **Fix sketch**: first write a one-page coverage comparison (endpoint → library call → equivalent
  semantics), then delete only what the comparison covers; keep `requests` only if a surviving endpoint
  needs a plain streaming GET, and record the decision so the next audit does not re-open it.

---

## Examined and rejected (for the index's "considered and rejected" section)

- **`services/_common.py` is not a premature abstraction.** One 16-line module with two production
  consumers replaced two private `_now` copies; the problem is coverage, not existence (see DEBT-01).
- **`quality._canonical_stem` / `integrity.IntegrityVerifier._canonical_stem` wrappers are not drift
  left over from plan 010.** They now delegate to `page_identity.canonical_stem` and deliberately carry
  *different failure contracts* (quality swallows `KeyError/TypeError/ValueError` → `None` + an
  `identity_invalid` reason, `quality.py:365-381`; integrity lets the exception reach its caller's
  guard, `integrity.py:672-675`). Both are documented in place and pinned by `tests/test_stem_contract.py`.
  Chesterton's fence holds — merging them would destroy the readers' distinct error semantics.
- **`TERMINAL_STATUSES` consolidation is complete and correct** at five of six sites
  (`coverage_report`, `scheduler`, `coordinator` ×3, `campaign`); only the `run.py` literal remains
  (DEBT-02). The prior audit's "4× frozenset" family is closed as a family.
- **`search_index.SearchIndex` (the manifest-backed `search.db` layer) is not dead code.**
  `cli/search.py:109` builds it under `--rebuild` with legacy filters and the module docstring
  (`search_index.py:5-7`) records the retirement plan. It is a recorded decision, not residue.
- **`curl_cffi` unused-by-`src` is not a removable dependency.** It is declared precisely because the
  pinned library imports it lazily, is documented at README `:1096-1102`, and is pinned by
  `tests/test_bilibili_api_gateway.py:2063` (fails if the declaration is dropped).
- **`quality.py`'s `import json` is not an orphan** (`quality.py:7`): suffixes are inspected, the module
  uses `difflib`/`math`/`collections` at `:622/:652/:660/:732`; no module-level `json.` call remains but
  the import is load-bearing elsewhere in the file's contract. Confirmed unused-import candidates in this
  pass were only the two in `cli/meta.py`.
- **God-module split of `storage/database.py` (2190 lines, 49 methods, 4 repository classes + module-level
  schema/connection helpers) and `search_index.py` (1651 lines, two index layers): examined, not
  recommended now.** Both are above the repo median (~400 lines/module) but their concern mix is
  nameable and documented, the delta's growth in `database.py` is a single cohesive writer
  (`record_local_transcript`, +137 lines), and a split would move ~10 import sites for no behavior
  change. The criterion that would flip this: if a second writer family is added to
  `MediaQueueRepository` (or the legacy index layer is retired per its own docstring), split then.
- **`[asr]` extra vs engine imports: consistent.** `asr.py:931` imports `transformers` (declared
  `>=5.13`), `:1175` imports `soxr` (declared), `numpy`/`soundfile` arrive as declared/transitive with
  the rationale written in `pyproject.toml`, and `torch`'s omission is the recorded recipe decision.
  No new mismatch in the delta.
- **`RequestTransport`-adjacent pins: no abandoned-pin claim made.** Release recency of
  `bilibili-api-python==17.4.2` was not checked (no network use permitted for this pass); the two rows
  above stay separate.

## Non-finding leads (for the captain, not for the report)

- **`I-000139` (is_stale journal-blind) looks already fixed in this delta**: `search_index.py:507-518`
  now takes `max(mtime)` over `(manifest_path, journal_path)` and the docstring names the journal.
  The row is probably closeable — verify by hand before closing.
- **`I-000028`'s premise is closed by plan 003**: its cited line `manifest.py:280` no longer describes
  the upsert cost, and the README paragraph in DOCS-02 still repeats the same O(N²) model. Fix the
  paragraph and re-scope the row together.
- **`I-000105`'s premise is closed by R14** in this delta (`record_local_transcript` now reaches the
  store from three CLI/coordinator paths); the *doc* that agreed with the old premise is DOCS-03.
- **`I-000157` (fixtures reading `manifest.jsonl` a journal-only upsert never writes) is the
  test-side face of DOCS-01** — a reader that assumes the snapshot is complete. Same root, different
  consumer; not re-reported.

## Truncated coverage

`Truncated coverage:` The following delta surfaces were **not** examined beyond grepping for names, and
no claim is made about them: `coordinator.py` (+507 — only its `record_local_transcript` and
`TERMINAL_STATUSES` call sites were read), `sidecar_projection.py` (+77, `replay_journal_records`),
`page_identity.py` (+56), the bodies of the `search_index.py` delta hunks (`~+173`), `integrity.py`
(+58), `quality.py`'s post-move internals beyond the `_canonical_stem` wrapper, the manifest journal's
crash/compaction windows (no probing was run — the mandate is read-only), and the test delta
(`_archive_database.py`, `test_storage_queue_writes.py`, `test_persistence_scale.py`, `test_search.py`).
Dependency analysis reached manifest-level comparison and installed-distribution metadata only: no
`pip-audit` (not installed, and installing is forbidden), no CVE check, and no upstream-release recency
check for the hard pin.
