---
iteration_id: iter-2026-09-qwen3-asr-closeout
start_date: 2026-09-25
status: completed
end_date: 2026-09-26
iteration_base_branch: main
target_branch: main
plans:
  - 20260924-qwen3-asr-transformers
---

# iter-2026-09-qwen3-asr-closeout — delivery compass

> **For agentic workers:** this compass is the context carrier for the Phase-1 review-and-edit chain
> (§1.6). The dispatched roles work from disk only and never see the PM session, so every decision,
> constraint, non-goal and open item they need is either stated here or reachable from a path named
> here. Items that still need a role's judgment carry a `TODO(owner: …)` marker; the marker syntax is
> defined in `mstar-iteration/references/phase-1-prepare.md` §1.3(iii) and is not restated here. The
> three-role chain has closed (see `## Phase 1 review chain`) with **no chain-owned marker left** and no
> open question left in `## Open Questions`; the one surviving marker is the `PM`-owned deferred-E2E
> item under `## Roadmap Position`.

## Scope

The engine switch is **already merged**: `feat/20260924-qwen3-asr-transformers` went into `main` as
`--no-ff` merge commit `3b561ea` (2026-09-25), and the ASR boundary now runs on
`Qwen/Qwen3-ASR-1.7B-hf` + `Qwen/Qwen3-ForcedAligner-0.6B-hf` through `transformers`, with no
FunASR code path left in `bilibili-asr-archive/src/`. This iteration does not re-open that work. It
closes the four items the merge left open, of which the operator placed three in scope.

In scope, in order:

1. **T5 — the hotword measurement.** Re-measure the corpus vocabulary under the engine that ships.
   The plan's T5 asked for a two-arm run; the operator fixed the arms (C3). The trigger is the open
   `high` residual `20260922-proofread-wave · R1`: the project's own scoring counts *surface
   occurrences*, so it cannot separate a hotword that was **recovered** from one that was
   **inserted** into a passage where the speaker said something else.
   `Check: ## Acceptance Criteria 1`.
2. **T6 — the archive's two-engine state.** Record the accepted decision (D12: the three legacy
   FunASR-era parts under `/mnt/e/asr-archive-20/` are **not** re-transcribed) where a reader of the
   frontmatter would look, so a later reader does not read it as a defect.
   `Check: ## Acceptance Criteria 3`.
3. **The unlocked decisions.** D5 (chunking constants), D6 (the hotword prompt surface), the
   `BILI_ASR_MODEL` default expression, and the throughput target were still `recommended` /
   unstated at merge time. Each becomes a named decision with evidence.
   `Check: ## Acceptance Criteria 4` and `## Acceptance Criteria 5`.

4. **Two repairs the measurement forced into scope.** T5 could not run on the corpus in its real
   container — the merged boundary read audio with `soundfile`, and libsndfile cannot decode the **AAC**
   inside the `.m4a` the archive's own downloader writes (C10, `R1`) — and the list it was to measure had
   been silently rewritten by the same merge, losing the six homophone entries including `扬弃` (C11, `R2`).
   Both are fixed and both are `high`. `Check: ## Acceptance Criteria 1`.

Out of scope: real-machine CLI E2E (operator deferred it — see `## Roadmap Position`), and everything
listed under `## Non-Goals`.

## Decisions

Engine decisions D1–D12 were settled by the operator on 2026-09-24 and are now **merged facts**, not
proposals. They are restated here because the dispatched roles cannot see the plan's history; the
plan carries the long-form rationale, measurements and rejected alternatives.

| # | Decision | Rationale | Source |
|---|----------|-----------|--------|
| D1 | Model is `Qwen/Qwen3-ASR-1.7B-hf` | Public quality on the Chinese dialect / tongue-twister / extreme-noise sets beats the retired Fun-ASR-MLT-Nano; Apache-2.0. | user instruction 2026-09-24 (plan §5 D1) |
| D2 | Route is **transformers-native**, hard cut: no dual-engine flag, no compatibility path. The chunker/stitcher was re-implemented inside our boundary after reading the reference package, which is **not** a dependency. | `qwen-asr 0.0.6` pins `transformers==4.57.6` and would silently downgrade the host's `transformers 5.16.1`; it also drags in `vllm` and a web stack. Rollback is `git revert`, not a runtime switch. | user instruction 2026-09-24 (plan §5 D2) |
| D3 | Timestamps come from `Qwen/Qwen3-ForcedAligner-0.6B-hf` plus our own chunker; no interpolation, no invented boundaries. | `generate()` returns text only; the aligner is the only source of timings and is ~250× cheaper than decode, so chunk size is tuned around decode cost. | settled by D1/D2; measured 2026-09-24 (plan §13.5) |
| D4 | **No confidence keys at all.** The engine emits no per-cue score, so the existing no-score path (`_confidence_summary` returns `{}` when no cue carries a numeric score) ships unchanged. | Reusing the old key names would be a silent contract redefinition: a FunASR mean token score and an autoregressive decoder's mean log-probability are different quantities. Omission is the honest record. | user instruction 2026-09-24 (plan §5 D4) |
| D5 | Chunking adopts the measured constants: 180 s windows carrying timestamps, boundary at the quietest point inside the target window, **exact tiling** (no overlap, no gap, no lost tail), 0.5 s zero-padding floor. The cap is `DEFAULT_CHUNK_SECONDS` (`bilibili-asr-archive/src/bili_asr/asr.py:52`), overridable only through `BILI_ASR_CHUNK_SECONDS` (`:93`; resolver `:241-253`, blank stays unset, non-positive refuses). The `1200 s / no timestamps` variant does not exist in this implementation. | The aligner's documented limit is 5 min and the reference implementation picks 180 s; the merged code already ships exactly these values, and §13.6 measured 16 chunks tiling a 47.4 min item exactly. | architect round 2026-09-25, at HEAD `9d530cd`. Shipped constants: `DEFAULT_CHUNK_SECONDS = 180.0` (`asr.py:52`), `_CHUNK_SEARCH_EXPAND_S = 5.0` (`:53`), `_CHUNK_MIN_WINDOW_MS = 100.0` (`:54`), `_CHUNK_MIN_SECONDS = 0.5` (`:55`), `SAMPLE_RATE = 16_000` (`:56`), with the aligner's bound stated at `:46-49`. Measured: plan §13.6 — one 47.4 min item through the merged boundary as 16 chunks of 146–185 s, tiling exact. The `1200 s / no timestamps` variant is **dropped, not deferred**: it cannot exist here because a chunk is a caller-supplied cap on a single aligned window, the aligner's documented limit is minutes, and no code path reads or wants a 1200-second constant (verified — `grep -n '1200' src/bili_asr/asr.py` matches nothing; the only cap is `DEFAULT_CHUNK_SECONDS` at `:52`). |
| D6 | The hotword list reaches the model as the processor's free-form `prompt` (`"Vocabulary: " + ", ".join(hotwords)`); an empty tuple sends no prompt. Confirmation of its *value* is T5's two-arm measurement, not a decode-time-bias assumption. | The list is one line of prompt context, not a decoder bias — the mechanism changed with the engine, so every cited hotword measurement from the FunASR era is stale. | user instruction 2026-09-24 (plan §5 D6); arms fixed by user instruction 2026-09-25 (C3); shipped expression verified at HEAD `9d530cd` — `asr.py:697` reads `prompt = "Vocabulary: " + ", ".join(self.config.hotwords) if self.config.hotwords else None`, so an empty tuple sends no prompt at all, and the list reaches the model only through `ASRConfig.hotwords` (`:195`). |
| D7 | Environment: the AMD/WSL ROCm recipe; the repo `.venv` and `/root/gpu-venv` are interchangeable on the target host. | Re-verified 2026-09-25 on `chosenecho@192.168.3.21`: with `HSA_ENABLE_DXG_DETECTION=1` **both** venvs reach the RX 7800 XT (gfx1101, 15.8 GB) and `scripts/check_asr_env.py` passes all five invariants with exit 0. The plan's `high` risk "repo `.venv` core-dumps under the DXG flag" did **not** reproduce. | measured 2026-09-25 (this iteration's reconnaissance) |
| D8 | New provenance keys are named under the repository's `naming-analyzer` discipline and documented in one contract, with a recorded decision, before they are written. | The archive's frontmatter is a public-ish contract; renaming or redefining a key without a recorded decision is a STOP condition (plan §8). | plan §5 D8 |
| D9 | Offline determinism: local snapshot directories, `HF_HUB_OFFLINE=1`, and the "no download helpers" guard stays green. No runtime network access on the ASR path. | Plan §7 Done 1 requires `bili-asr asr` to transcribe with no runtime network; the guard is an existing test obligation. | plan §5 D9 |
| D10 | Weights live **in-project** under `bilibili-asr-archive/models/` (gitignored), fetched through `hf-mirror.com`, verified against the published LFS sha256 before use. | `huggingface.co` timed out from the target host; the mirror delivered 7.58 MB/s. Digests are recorded in the plan's §12 appendix. | user instruction 2026-09-24 (plan §5 D10) |
| D11 | bf16 only, no quantization. Re-evaluate only against the measured throughput trigger (C4), with the plan §5 acceptance gate: identical transcript on a fixture, no crash, end-to-end timing. | 1.7B bf16 is 4.08 GB in a 15.8 GB card — no memory pressure — and every quantisation kernel with a real ROCm story costs a transformers downgrade. | user instruction 2026-09-24 (plan §5 D11) |
| D12 | The existing transcripts are **not** re-transcribed. The three parts already archived under `/mnt/e/asr-archive-20/` keep their FunASR-era provenance, and the archive will hold text from two engines. This is accepted, not a defect. | Re-running 3+ hours of audio to unify provenance buys nothing the reader can use; the honest move is to record the acceptance where the reader looks. | user instruction 2026-09-24 (plan §5 D12); recording owed to T6 |
| C1 | This iteration is a **closeout** with a **single plan row**: the existing plan file `.mstar/plans/20260924-qwen3-asr-transformers.md`, which documents both the merged switch and the open items. | The plan is the artifact the operator named; splitting it would orphan the measurements in §13 that the remaining work rests on. | user instruction 2026-09-25 |
| C2 | Branch policy: base `main`, integration `iteration/iter-2026-09-qwen3-asr-closeout`, target `main`. | The repository's `AGENTS.md` sets the default integration/PR target to `main`, and feature work merges into `iteration/<iteration-id>`. Explicitly confirmed, not silently defaulted. | user instruction 2026-09-25 (`## Delivery Branch Policy`) |
| C3 | T5's two arms are **single-engine**: the shipping engine **with** the hotword prompt versus the same engine **without** it. A cross-engine comparison against the stored FunASR-era text is **not** a deliverable. | The mechanism by which the list reaches the model changed, so the question "does the list pay for itself under *this* engine" is the only one the measurement can settle cleanly. The old text stays on disk as corroboration. | user instruction 2026-09-25 |
| C4 | Throughput gate: **≤ 0.4× real time**, end-to-end, on the reference item. Exceeding it triggers the D11 quantisation re-evaluation. | Measured baseline is 0.151× (§13.6: 47.4 min item, wall 428 s); 0.4× is the operator's ceiling before quantisation is back on the table. | user instruction 2026-09-25 |
| C5 | The measurement and the host check run on `chosenecho@192.168.3.21` (WSL, gfx1101). This is the operator's **explicit authorisation** to run them on that device, recorded here because a development plan may not otherwise carry device evidence. It is a measurement environment, **not** a real-machine E2E acceptance gate. | The operator asked for the test to happen there; `mstar-harness-core` puts real-machine E2E behind a separately started `mstar-e2e` workflow, which is why the distinction is written down rather than assumed. | user instruction 2026-09-25 |
| C6 | T5's "six-item corpus" is the six UID-23191782 parts that the proofread wave already used: `BV11p5qzAE6s`, `BV1BdtazGEBE`, `BV1iddQYQE7D`, `BV1vNTqzFEve`, `BV1Y7M4zNEfF`, `BV1zz5zzFENq` — 26 282 s ≈ 7.30 h, audio at `/mnt/123pan/bili-asr-e2e/asr-vs-subtitle/audio/<bvid>.p0.m4a`. The FunASR-era transcripts of those same parts are already on disk (evidence, not a deliverable). | The plan's T5 wording ("six-item corpus") is ambiguous between the proofread corpus and the `e2e-23191782-*` video set; reconnaissance showed they are the same six parts, so the ambiguity is resolved rather than carried. | reconnaissance 2026-09-25; plan §6 T5 |
| C7 | The control host has **no engine store** (`.mstar/store.db` absent, `store.not-initialized`). Residual accounting therefore happens on the surfaces that exist: the plan's residual section, the project register file, and the target artifact frontmatter — never by pretending a store-backed issue was filed. | Engine-absent route: the same constraint that has every lifecycle write hand-written to the frozen contract. Reading `store.not-initialized` as "nothing to close" is explicitly forbidden. | `mstar-harness-core` §1.1; measured 2026-09-25 |
| C8 | T6's accepted two-engine state is carried by two reader surfaces: the **authoritative** one is a subsection of `bilibili-asr-archive/README.md`'s provenance material, stating that the three FunASR-era artifacts under `/mnt/e/asr-archive-20/` keep their FunASR text by operator decision (D12) and why that is accepted rather than a defect; a **supporting** row in `.mstar/projects/_default/residuals.json` points at it for readers who work from the register. | The plan's own §6 T6 already requires the record to land in the docs and in the residual register; naming the authoritative surface prevents two half-statements a reader must reconcile. C7 constrains the wording: this host has no issue store, so the register entry is a file row, never a claim that an issue was filed. | product-manager round 2026-09-25 (was Q3) |
| C9 | This closeout owes **no** `{SPECS_DIR}/` change. The `asr-archive-cli.md` revision note of 2026-09-24 is the mechanism and already covers the stale engine text: it declares the frozen body "kept as written" and states that Goals 4, the module map's `asr.py` line and the whole `[asr]` dependency boundary are superseded by `bilibili-asr-archive/README.md` and by the migration plan. The lines at `:92-98` are therefore deliberate historical record, not drift, and are not edited. | Correcting them in place would contradict the revision note's own "kept as written" policy and would change text inside the spec's change-policy zone, which needs a new spec revision plus PM sign-off for requirement changes — neither is owed here. Supersession by reference already answers the reader. | product-manager round 2026-09-25 (was Q4); verified against `asr-archive-cli.md:7-17` |
| C10 | **A codec repair was added to scope mid-iteration.** The merged boundary could not read the audio the archive's own downloader writes: `transcribe()` read with `soundfile`, and libsndfile reads WAV/FLAC/OGG/MP3 but not **AAC**, the codec inside the `.m4a` `cli.py:1574` / `audio.py` produce. `_read_audio()` now keeps `soundfile` primary and falls back to `librosa` on `LibsndfileError`; four tests pin the boundary. | The measurement could not run on real audio otherwise, and the defect is the product failing to read its own storage format, so it is not separable from delivering T5 honestly. `librosa` was already a declared `[asr]` dependency and already imported by that module, so no dependency was added and no STOP condition fired; the fix is registered as `20260924-qwen3-asr-transformers · R1` (high). | found and fixed 2026-09-26 in the T5 execution round; commit `0a95035` on `feat/20260924-qwen3-asr-transformers`. Evidence: `sf.read` raises `LibsndfileError` on a corpus `.m4a` while the FLAC transcode archives; `librosa.load` of that `.m4a` is sample-identical to `ffmpeg -ar 48000 -ac 2` (zero length difference, max abs diff `0.000000`); the 2026-09-24 measurement was green only because it ran on a PCM `.wav` |
| C11 | **The hotword list was restored to its documented 33 entries, and T5's thresholds restated.** `2548ca9` silently deleted the six 2026-09-17 homophone entries incl. `扬弃`, re-added `ITEM`/`AITEM` after `ef5e1e8` removed them for measured harm, and dropped the three Latin shards — 33 entries to 26, with no authorisation, no commit mention, no test, and a README still documenting the old list. Restored in `83ba8d0`; the protocol carries an **Amendment 1** restating `R ≥ 33` and why the old 26 was wrong. | T5 measures whether the list earns its place, so it cannot measure a list that changed for no recorded reason; and `扬弃` is the one term the 2026-09-18 precedent measured (+34 recoveries), so restoring it makes that precedent bear on P1 instead of being excluded from it. | found and fixed 2026-09-26 in the T5 execution round; registered as `20260924-qwen3-asr-transformers · R2` (high). Evidence: parsed `2548ca9^` = 33 entries vs `HEAD` = 26, same comparison after the fix = identical set and order; `git log -S` attributes each change; `README.md:178-196` contradicted the code in all three respects |
| C12 | **The T5 instrument was audited before it was trusted, and its scope for the short set is declared, not discovered.** The three short arms passed the product's own `verify` (0 defects) plus 12/12 independently recomputed artifact hashes before any verdict was read from them (guide `guides/t5-artifact-audit.md`). The ≤10 min corpus is three items (`BV1aRTA6mEGF` 571 s, `BV132XgBjER4` 500 s, `BV1wLTP6NE9h` 449 s — the complete ≤600 s set, taken whole) carrying **E = 5** caption-attested terms, so by the protocol's own P9 its P1/P2 are **uninformative** and the six `R2`-restored terms are **untestable** there (0 occurrences across all eleven short items on disk); P5–P8 and C4 remain informative. | The frozen six-item corpus cannot be shortened — its shortest item is 34.8 min — so a sub-ten-minute request needs either a second corpus or no answer. Admitting one only works if its limits are fixed before the run, otherwise a weak PASS reads as a verdict; and the first real run showed why the instrument itself must be audited: its arm products were conformant, but its *driver* carried a git-anchored restore that would have silently reverted the 33-entry fix and still reported the run sound. | recorded 2026-09-26 as protocol **Amendments 3 and 3a**; driver hardened to a byte-anchored restore with a pre-run term-count guard; `R1`'s tracking extended with the observed decode chain (`librosa` → `audioread` → `ffmpeg`) |
| C13 | **The short corpus ran and its result is recorded with its limits.** Three items ≤600 s, 1 520 s total, 33 items of 26 min: A/B/R arm identity 33/0/33 read back from frontmatter; **P6** 0.98107, **P7** 1.000000 with all three items byte-identical A-vs-R, **P8** clean, **C4** 0.1803×/0.1434×/0.1467× — all four PASS. **P1/P2 uninformative** (E=6 < 8, per P9) and **P5 unsettled** (`fabrications()` is a declared placeholder). Result on this corpus: **R=0** — the prompt recovered nothing and produced one candidate `马恩牌` insertion on `BV1wLTP6NE9h`. | A measurement whose limits are not fixed before the run gets read as a verdict; and the run had to survive two instrument defects of its own — a restore that would have silently reverted the fix (Amendment 3a) and a census that over-reported R by matching arm B on exact timestamps. | guide `guides/t5-hotword-short-corpus-results.md`; `R1`-class candidate insertion recorded with its span; instrument defects documented in §6 of that guide so neither can be re-introduced silently. |
| C14 | **The frozen six-item corpus was lost to a mount failure, a substitute nine-item corpus ran in a new location, and the driver was hardened so the loss cannot recur.** `short2` = 9 items ≤600 s (the sweep's remainder after removing the 3 already measured), 4 101 s/arm, staged under `/mnt/e` (local disk, no WebDAV dependency) with arm roots in a separate tree. **P6** 0.980279, **P7** 1.000000 all nine byte-identical, **P8** clean, **C4** 0.157/0.116/0.117× — all PASS; **R = 0, I = 0, E = 3** ⇒ P1/P2 uninformative (P9), P5 unsettled. | The six C6 items are the only instrument that can settle P1/P2, so losing their audio is a scope-threatening event and had to be recorded, not worked around. Substituting a corpus without declaring its coverage would let a PASS read as a verdict. And the loss was self-inflicted: `setup` deleted before verifying its source, while the operator already knew the mount was unreadable. | guide `guides/t5-hotword-short2-corpus-results.md`; register row `20260924-qwen3-asr-transformers · R3` (high, open for re-staging); driver now verifies the audio source before deleting, reuses staged arms, needs `FORCE_SETUP=1`, and its corpus→bvid guard covers all three corpora |
| C15 | **T5 ran on the frozen six and returns `PARTIAL`, with a negative result on the list's effect.** 6/6 items both arms, 7.3 h, thresholds fixed in advance, restore byte-proven. **R = 0, I = 0** — every one of the 7 exercised terms has an identical count in both arms, incl. four of the six `R2`-restored homophones, whose FunASR-era failure does not reproduce under the shipped engine. **P6 FAILS** at 0.941523, traced by hand to a reproducible **English degeneration loop in the prompted arm** on `BV1iddQYQE7D` (one 5 289-char cue in a 3.9 s window; `blowing` ×99, `thatis` ×41), which the unprompted arm does not have and which arm R reproduces byte-for-byte. P3/P4/P7/P8/C4 pass. **`PARTIAL`** on P9's `E = 7 < 8` ground. | The protocol requires a negative verdict to be recordable, not softened — and this is one: the list changed nothing measurable about any term on the corpus it was built for. It must be read narrowly: `E < 8` means the corpus cannot settle the list's worth, and whether the prompt *causes* the degeneration is raised, not closed. | guide `guides/t5-hotword-measurement-results.md`; the P8 gap it exposed is recorded in that guide's §6, not patched, because thresholds are frozen for this measurement. |
| D13 | The default expression is the hub id, and the operator overrides it locally. `ASRConfig.model_name` defaults to `Qwen/Qwen3-ASR-1.7B-hf` and `aligner_name` to `Qwen/Qwen3-ForcedAligner-0.6B-hf` (`bilibili-asr-archive/src/bili_asr/asr.py:36-37`), applied as `os.environ.get(BILI_ASR_MODEL) or DEFAULT_MODEL` (`:281-282`); a local directory is accepted at run time but is **never** a provenance identifier (`README.md:113-118`: point the two variables at pre-populated local directories for offline use, nothing is fetched at run time), so the delivered archive records identity only through `BILI_ASR_MODEL_ID` / the redacted `asr_model_name` slot (`README.md:137-161`, the three-variables section; `asr.py:810`). A local override does **not** contradict the hub-id default, and no doc promises a path default. | The default must be decidable with no environment and no local layout, so a hub id is the only value that can be a default; the offline promise is about the *fetch*, which the operator's override answers, and the identity is a separate slot so the two never have to be the same string. Rejected: defaulting to `models/Qwen3-ASR-1.7B-hf` (env-dependent, silently wrong on any checkout that has not fetched) and promising deferred fetching (contradicts D9). | architect round 2026-09-25 (was Q1); cites `asr.py:36-37`, `asr.py:281-282`, `README.md:113-118`, `README.md:137-161` |
| D14 | T5's measurement is run exactly as pre-declared in `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-protocol.md`: two single-engine arms (shipped prompt vs `DEFAULT_HOTWORDS` temporarily reduced to the empty tuple), the reference item first, the recorded command, the numbered thresholds P1–P9, the census paths and the verdict mapping all fixed there before any arm runs. Two non-negotiables: thresholds are fixed **before** measuring, and arm B is built by temporarily deleting the `DEFAULT_HOTWORDS` literal (`asr.py:100-105`) — an environment variable cannot do it, since `_extra_hotwords` (`:257-266`) only ever adds — with the restore proven **twice** (scoped `git status --porcelain` clean **and** working blob hash equal to `HEAD`'s) and arm identity read back from the artifacts' `asr_hotwords` frontmatter key (`asr.py:815`, `archive.py:492-493`). | Thresholds chosen after seeing the data measure nothing, and a forgotten restore ships a changed vocabulary silently; both are the failure modes the knowledge note and the compass risk register already name, so they are protocol clauses rather than advice. | architect round 2026-09-25 (was Q2); protocol guide named above; `{KNOWLEDGE_DIR}/testing-patterns/hotword-list-measurement.md` |

`<!-- architect round 2026-09-25: this marker is cleared. D5 and D6 are named in place (shipped constants with `file:line`, the §13.6 tiling measurement, the dropped `1200 s / no timestamps` variant, the shipped prompt expression); Q1 and Q2 converged into D13 and D14 immediately after C9; the T5 protocol is pre-declared in `{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-protocol.md`. -->`

## Open Questions

| # | Question | Owner | Blocking? |
|---|----------|-------|-----------|

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| `20260924-qwen3-asr-transformers` | Switch the ASR model and inference engine to Qwen3-ASR on transformers | Done | T1–T4 merged in `3b561ea`; T6 **done** 2026-09-26 (`7b86882`, register `R4`). T5 produced two substitute-corpus reports but **the frozen six-item corpus remains unrun** — its audio was lost 2026-09-26 (`R3`, high), so P1/P2 are still unreached. Two defects the measurement forced into scope are fixed (`R1` codec, `R2` hotword list). §14 item 4 (real-machine CLI E2E) stays deferred by the operator. Detail below. |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

The plan is the iteration's only plan row. Its §14 records the merge and lists the open items; its
§5–§9 carry the decisions, tasks, Done criteria, STOP conditions and risks that T5 and T6 execute
against; its §13 carries the measurements this closeout builds on. Its §10 is reconciled as part of this Phase 1:
both entries its draft carried are now settled — D4 in the plan's own §5, and D5, D6 and the
default expression as named decisions in this compass's `## Decisions` table (D5, D6, D13).


## Milestones

| Milestone | State |
|-----------|-------|
| Spec freeze (Phase 1 lock) | done 2026-09-25 — chain closed, round 3 (`writing-specialist`) landed; `status: locked`. No `{SPECS_DIR}/` change was owed (compass row C9) |
| Dev complete (plan Done) | pending |
| QC complete | pending |
| Iteration close | pending |

## Acceptance Criteria

1. **The two-arm hotword measurement exists, with its basis declared.** Both arms' `asr_hotwords`
   read back from the written archive's frontmatter; the "without" arm's restore proven twice; the
   verdict separates **insertions** from **recoveries** rather than counting surface occurrences;
   thresholds were fixed before measuring; a same-config repeat gives the noise floor. Run on the
   target host (C5) over the six-part corpus (C6), with inputs (arms, commit, host, command)
   recorded.
2. **The host check passes where ASR runs.** `scripts/check_asr_env.py` exits 0 in the environment
   that transcribes, that environment is named in `bilibili-asr-archive/README.md`, and the weights
   are in-project and match their published digests (plan §7 Done 5).
3. **The two-engine state is recorded where a reader looks.** A reader of one of the three legacy
   parts' frontmatter (or of the README's provenance section) learns that text from two engines is
   accepted, and why, without having to reconstruct it (plan §7 Done 6/D12, T6).
4. **The unlocked decisions are named, not left as "recommended".** D5's constants, D6's prompt
   surface, the default-expression decision (D13) and the throughput target each appear as a
   decision with its evidence and, where the value is a shipped constant, a `file:line` citation.
5. **The throughput gate is answered.** End-to-end real-time factor on the reference item is
   recorded against the 0.4× ceiling (C4). If it exceeds the ceiling, the D11 quantisation
   re-evaluation is triggered and its acceptance gate (identical transcript on a fixture, no crash,
   end-to-end timing) is run — or the iteration reports the gate as failed. A silent pass is not an
   outcome.
6. **One engine in one place.** The docs and the frozen spec describe a single engine; no test
   asserts FunASR remains; the engine-independent suite is green on the target host (plan §7
   Done 6–7).
7. **The `high` residual is moved, not ignored.** `20260922-proofread-wave · R1` is closed or
   narrowed, and the measurement's verdict on it — including a negative one — is written into the
   plan's residual section. C7 governs where a "filed issue" claim may point.

## Non-Goals

Each non-goal carries the reason it is excluded, so a later reader does not read the omission as
oversight.

- **Real-machine CLI E2E.** The operator deferred it (plan §14 item 4). It belongs to a separately
  requested `mstar-e2e` workflow run on the target host; carrying it here would make a development
  plan the bearer of device evidence, which the directed-execution boundary forbids. See
  `## Roadmap Position`.
- **Quantisation (int8/int4/GGUF/FP8/NVFP4/OpenVINO).** No quantised Qwen3-ASR-1.7B artefact loads
  under `transformers` with a real ROCm story, and each candidate costs an engine downgrade (plan
  §5 D11). Re-opened **only** by the C4 throughput trigger.
- **vLLM and FlashAttention-2.** A STOP condition (plan §8) — they must not enter the dependency set.
- **Streaming inference and fine-tuning.** Outside the product's scope (plan §11).
- **Re-transcribing the three legacy parts.** D12 accepted the mixed-engine archive deliberately.
- **The editorial stages, the manifest, the store and the publication boundaries.** Parked, separate
  scope; the `iter-2026-09-transcript-editorial-stages` harness package was deleted on 2026-09-25 and
  is not restored by this iteration (plan §11).
- **Adding files to `{KNOWLEDGE_DIR}/` during start/execute.** Promotion happens once, at
  iteration-close, via `mstar-compound`.

## Roadmap Position

- **Current iteration: `delivered`.** Closed the Qwen3-ASR engine switch — the hotword measurement under
  the shipping engine (T5, verdict `PARTIAL`: `R=0`, `I=0`, P6 fail on a hand-read prompted-arm
  degeneration, `E=7` leaving P1/P2 uninformative), the recorded two-engine archive state (T6), and the
  four decisions the merge left as "recommended" or unstated. Two defects the measurement forced into
  scope were fixed (`R1` codec, `R2` hotword list) and the high residual `20260922-proofread-wave · R1`
  was closed. Merged into `iteration/iter-2026-09-qwen3-asr-closeout` as `d273242`.
- **Next iteration:** **real-machine CLI E2E** on `chosenecho@192.168.3.21`, as a separately started
  `mstar-e2e` workflow with its own workflow id (owner: the operator starts it, PM orchestrates,
  `ops-engineer` executes with `Delegation: forbidden`). Trigger: this iteration closed and merged,
  with the environment named in `README.md` and `check_asr_env.py` passing there (Acceptance
  Criteria 2). Scenario to name at that time: `bili-asr asr` end-to-end against one real episode on
  the documented host layout, with the side effects it is allowed to produce.
  `<!-- TODO(owner: PM): when this iteration closes, restate the E2E scenario and its allowed side effects at the point the operator starts it; the deferred item's scope is the operator's to fix, not the plan's to invent. -->`
- **Standing discipline:** the second open roadmap item from the plan's §14 — the residuals left by
  the deletion-era cleanup and the parked editorial iteration — stays outside this closeout unless it
  blocks one of the three in-scope items.
- **Final goal:** one engine, documented in one place, runnable offline from digest-verified
  in-project weights, with the hotword list's worth measured under the engine that ships and the
  archive's mixed-engine history honestly recorded rather than smoothed over.

## Delivery Branch Policy

| Field | Value | Source |
|-------|-------|--------|
| `iteration_base_branch` | `main` | user confirmation 2026-09-25; repository `AGENTS.md` default |
| `spec_integration_branch` | `iteration/iter-2026-09-qwen3-asr-closeout` | derived from the iteration id (`iteration/<iteration-id>`) |
| `target_branch` | `main` | user confirmation 2026-09-25; repository `AGENTS.md` sets the PR target to `main` |

**Main worktree branch**: `main` (observed at Phase-1 reconnaissance on 2026-09-25; the control
root stays on `main` and the integration worktree is a separate linked checkout).

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| T5's "without" arm needs a temporary source edit (`DEFAULT_HOTWORDS` deleted), and a forgotten restore silently ships a changed vocabulary. | medium | high | Follow `{KNOWLEDGE_DIR}/testing-patterns/hotword-list-measurement.md`: prove the restore twice — `git status --porcelain` clean on `asr.py` **and** the working blob hash equal to `HEAD`'s — and prove arm identity by reading `asr_hotwords` back from the artifacts. |
| The prompt-delivered hotword list may inject more than it recovers — the residual that triggered this work is exactly that failure mode. | medium | high | The two-arm design measures insertions separately; a negative verdict is a legitimate outcome and must be recorded as one (Acceptance Criteria 7). |
| The six-part corpus is 7.30 h of audio; at the measured 0.151× the decode alone is ~1.1 h, so the measurement can be interrupted or half-run. | medium | medium | Run the reference item first, record per-item results as they land, and report partial coverage as partial rather than extrapolating. |
| Two runs on the target host could be confused for each other (two venvs are interchangeable there). | low | medium | Record the environment per run and name which venv executed it; `check_asr_env.py` output is per-run evidence (Acceptance Criteria 2). |
| The plan's stale §10 still says D4 blocks T3; a reader could re-open a settled decision. | high | low | The plan-reconciliation marker on `## Plans` is cleared in the same review chain; the reconciled plan is the record that ends the contradiction. |
| The engine-absent route means lifecycle writes are hand-written; a wrong field could make the snapshot unreadable. | low | medium | Every write is validated with the engine's own validators before it is treated as landed, as in the previous iteration's environment note. |

## Phase 1 review chain (§1.6)

One row per round, written from that round's own completion report as it landed:
`product-manager` → `architect` → `writing-specialist`, in that order, each editing these documents in
place. `status: locked` is written only after the writing-specialist's hygiene pass and the marker sweep.

| # | Role | Findings | Cleared markers | Reassigned to PM |
|---|------|----------|-----------------|------------------|
| 1 | `product-manager` | Gave the plan its identity frontmatter; replaced the false "draft plan / not sealed / nothing registered" header with the registered status; rewrote §10 so it no longer claims D4 blocks T3 (D4 was settled in the plan's own §5) and so it names where the remaining decisions live. Converged **Q3 → C8** (T6's reader surfaces: `bilibili-asr-archive/README.md` provenance material authoritative, one register row supporting) and **Q4 → C9** (no `{SPECS_DIR}/` change is owed: the spec's 2026-09-24 revision note already supersedes the stale engine text by reference and declares the frozen body kept as written — correcting `:92-98` in place would contradict the note and enter the spec's change-policy zone). Both rows withdrawn from `## Open Questions`. | 1 — its own marker on `## Plans` | 0 |
| 2 | `architect` | Named **D5** and **D6** with `file:line` evidence: the shipped chunking constants and the explicit finding that the `1200 s / no timestamps` variant is **dropped, not deferred** (no such constant exists; the cap is `asr.py:52`, override `:93`/`:241-253`), and the shipped prompt expression at `asr.py:697`. Converged **Q1 → D13** (the default is the hub id, the operator overrides it locally, identity travels only through `BILI_ASR_MODEL_ID` / the redacted `asr_model_name` slot) and **Q2 → D14** (the measurement runs exactly as the pre-declared protocol). Wrote `guides/t5-hotword-measurement-protocol.md` (254 lines): arms, command, thresholds P1–P9 fixed before any arm runs, twice-proven restore, noise floor, artifact paths, verdict mapping. Removed the stale cross-reference to a marker that no longer existed. | 1 — its own marker on the decisions table | 0 |
| 3 | `writing-specialist` | Wrote this package's `README.md` (35 lines): one-line charter, an `## Orientation` pointing at the compass first and the guide second, `specs/` stated empty rather than invented, and an empty `## Promotion log` for iteration-close. Ran the hygiene pass: `{SPECS_DIR}/` unchanged and its index accurate, no new `{KNOWLEDGE_DIR}/` document, no iteration draft misplaced into `{SPECS_DIR}/`, no flat legacy guide/compass file at the iterations root, and the iteration's index row resolves. Marker sweep: no `product-manager` or `architect` marker remained. Reported the plan-level contradiction the earlier rounds had left. | 1 — its own marker on `## Iteration package` | 0 |

**Chain-owned markers: zero remain.** The one surviving marker is `TODO(owner: PM)` under
`## Roadmap Position`, which is the deferred real-machine E2E item — its scope is the operator's to fix at
the point the workflow starts, so it is correctly held to iteration close rather than invented here.

**Plan reconciliations the chain found and closed.** After the architect named D5/D6, three cells in the
plan still described a `1200 s` chunk branch as live, and two more still read `recommended`. The
product-manager round replaced the §5 D5/D6 cells with the settled decisions, collapsed §13.3's two chunk
branches to the single timestamped one, restored the §5 D7 cell to the re-verified environment decision,
and annotated §14 item 3 to name D5/D6/D13/D14/C4 while keeping the item (those decisions still have to be
*delivered* under T5/T6). The two lines that describe the **reference package's** constants (`:77`) and a
**dated** measurement item (`:424`) were deliberately left as they are: they are historical record, not
live claims.

## Iteration package

| Path | Contents | Editing roles |
|------|----------|---------------|
| `guides/` | Iteration-level working notes and measurement guides that are not long-lived contracts. | product-manager, architect |
| `specs/` | Iteration-level specs for this closeout. Long-lived specifications stay in `{SPECS_DIR}/`. | product-manager, architect |
| `README.md` | Optional prose orientation for the package. Not a register, and not a one-row-per-document table. | writing-specialist |

The writing-specialist round closed this item by writing this package's `README.md` and running the
hygiene pass; the chain's rounds and their outcomes are recorded in `## Phase 1 review chain`.

## Quality Gate Summary

**Phase 2 close.** The plan `20260924-qwen3-asr-transformers` is `Done` (snapshot, 2026-09-26); this
iteration has one plan row and no others.

| Gate | Result |
|---|---|
| Plan status | `Done` in the snapshot and in `## Plans` above (synced) |
| Acceptance Criteria | **7 of 7 met**; the dispositions are the close record — AC1 T5 verdict, AC2 host/env/digests, AC3 two-engine record, AC4 decisions named, AC5 throughput 0.1465× vs the 0.4× ceiling (D11's re-eval **not** triggered), AC6 suite green, AC7 residual closed |
| Test suite (target host) | **1704 passed, 6 skipped, 5 errors** — the 5 are the pre-existing installed-entrypoint cases needing `uv`/`setuptools`, unrelated to this iteration |
| ASR suite (target host) | `tests/test_asr_qwen.py` **40 passed**, incl. the offline guard `test_transcription_imports_no_network_module` |
| Artifact verification | `verify` 0 defects on all six items of arm A; the three-arm artifact audit records 12/12 hashes and four-surface agreement (short corpus) |
| Restore discipline | byte-anchored, **proven** on all three corpora (the six-item run, the short set, the second short set) |
| Branch / PR base | integration `iteration/iter-2026-09-qwen3-asr-closeout`, target `main` — recorded in the snapshot and in `## Delivery Branch Policy` |
| Merge into integration | `d273242`, pushed (`9d530cd..d273242`) |

**Residual disclosure — each plan's open `R#` list** (`Findings cleanup: allow-residual`, the iteration
Phase 2 default; unresolved `critical` blocks close — **none exist here**):

| Row | Severity | Tracking location | Blocker-defer? |
|---|---|---|---|
| `20260924-qwen3-asr-transformers · R1` | high | register `lifecycle: open`; fixed in `0a95035`, disclosed in the README's decode subsection; the owed follow-up (a fixture that round-trips a real `.m4a`) is named in its own `tracking` | no |
| `20260924-qwen3-asr-transformers · R2` | high | register `lifecycle: open`; fixed in `83ba8d0`, disclosed in README provenance; the missing test that pins the list's contents is named in its `tracking` | no |
| `20260924-qwen3-asr-transformers · R3` | high | register `lifecycle: open`; the six items were **re-staged** the same day and T5 ran on them; what remains open is that the loss itself (a mount whose reads fail while listings succeed) is not structurally prevented outside this script | no |
| `20260924-qwen3-asr-transformers · R4` | low | register `lifecycle: open`; documentation row, closed by being recorded (README subsection + this register) | no |
| `iter-2026-09-qwen3-asr-closeout · R5` | high | register `lifecycle: open`; **found by this iteration's own PR review after the close artifact was written**, so it appears in no earlier row. Fix plan `.mstar/plans/audit-2026-09-26/001-fix-aac-decode-contract.md` (P1, M); PR [review](https://github.com/SuperCatQR/bilibili-asr-archive/pull/19#pullrequestreview-5326843725) | no |

Also moved: `20260922-proofread-wave · R1` (high) — the residual this iteration existed to advance — is
**closed** (`lifecycle: resolved`, 2026-09-26) on T5's verdict, with its uncovered leg named in the closure
note rather than left to be inferred.

**Post-merge addition — `R5`, and why the lifecycle closed with it open.** The deep PR review of #19 ran
*after* the close artifact was committed and returned `blocked`: 1 must-fix, 5 should-fix, 6 nits
([review](https://github.com/SuperCatQR/bilibili-asr-archive/pull/19#pullrequestreview-5326843725)). The
must-fix is real and not cosmetic — the `.m4a` codec fallback is inert under the `librosa` version this
repo's own declarations resolve, so a rebuilt host does not get the repair the PR shipped — but it does not
touch this iteration's deliverables (the T5 measurement, the T6 record, the compound round), and the host
where the work ran uses `librosa 0.11.0`, where the fallback works. **The operator authorized merging anyway
and carrying the finding forward** (2026-09-26), so PR #19 merged as `1f2dcd0` with `R5` open rather than
expanding the iteration's scope. `R5` is therefore an **accepted-open** residual on `main`, deliberately not
closed here: reconciliation aligns projections to the terminal snapshot and does not close real findings to
make a lifecycle look clean.

---

## Compound Round Summary

**Package inventory** (`{ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/**`, compass excluded, 9 files):

| File | Disposition |
|---|---|
| `guides/t5-hotword-measurement-results.md` | **Keep snapshot** + trace marker added; its method content is promoted into the knowledge doc below |
| `guides/t5-hotword-measurement-protocol.md` | **Keep snapshot** — the pre-declared clauses P1–P9 belong to this measurement's record |
| `guides/t5-hotword-short-corpus-results.md`, `…-short2-corpus-results.md`, `…-short-item-dry-run.md` | **Keep snapshot** — substitute-corpus records; their shared lesson is promoted |
| `guides/t5-artifact-audit.md` | **Keep snapshot** — the contract audit of these arms |
| `guides/assets/ab-hotwords-qwen3.sh`, `guides/assets/census.py` | **Promote (as referenced tooling)** — named in the knowledge doc as the reusable arm driver and classifier; the files stay in the package |
| `README.md` | **Keep snapshot** — the package index |

**Promoted** (two docs, both **updated rather than created** — Q5 high overlap, the skill's fast rule):

| Doc | Plan | Change |
|---|---|---|
| `{KNOWLEDGE_DIR}/testing-patterns/hotword-list-measurement.md` | `20260918-transcript-text-precision`; `20260924-qwen3-asr-transformers` | 2026-09-26 findings section (negative result, `E=7` floor, prompted-arm degeneration), the byte-anchored restore correction replacing the git-shaped proof, method additions (pre-declared clauses, statement of arm order), and five further traps; frontmatter, tags and index row updated |
| `{KNOWLEDGE_DIR}/best-practices/premise-freshness-before-lock.md` | `20260920-transcript-projections`; `20260924-qwen3-asr-transformers` | the same principle's **irreversible** case: probe before you delete, prefer reuse over rebuild, and why a cached listing is not evidence of a readable source |

**Not created, with reason:** no new doc for the codec defect or the hotword-list restoration. Both are
project-specific defects whose durable lesson is already carried by the two docs above (the decode
dependency lives in the README's operator surface; the "a green suite cannot see a changed constant" lesson
is trap 6). Creating a third doc would have duplicated them — the skill's Q5 rule.

**No `CONCEPTS.md` update:** no new domain vocabulary this round.

**Validator note:** `mstar_compound_validate` returns **PASS** for both docs against `repo_root`. With
`knowledge_dir` added it returns FAIL, and so does an **untouched** doc — the catalog-completeness query
needs `.mstar/store.db`, which is absent here (`store.not-initialized`, the condition compass C7 records).
Per C7 the accounting therefore stays on the surfaces that exist; no store-backed check is claimed to have
run.

---

## Iteration Retrospective (minimal)

**What went well.** The pre-declared clauses carried their weight twice: the interpretive floor stopped a
null being read as a verdict, and the outlier rule — not any damage clause — is what found the prompted-arm
degeneration. The artifact audit ran *before* the verdict was read from the arms, so a bookkeeping error
could not have masqueraded as a transcription finding. Re-fetching the six with an identity cross-check
before downloading turned a loss into a recoverable step.

**What cost the most.** Two self-inflicted failures, both from acting on a premise already known to be
stale. The 123pan mount was **known** to be unreadable (401 on every read) and the script's `setup` was
still run against it, destroying the staged six (`R3`). And the restore proof was git-shaped on a tree
whose fix was uncommitted, so it would have passed while reverting the fix. Both are now rules in the
knowledge base rather than memories: probe before you delete; anchor a restore to bytes.

**What the measurement actually says, narrowly.** On 7.3 h of the corpus the list was built for, the
33-term prompt recovered nothing and inserted nothing, and the FunASR-era homophone failure that justified
restoring the six does not reproduce under the shipping engine on this corpus. `E = 7` is below the
protocol's own floor, so this does not settle whether the list earns its place — and the one item that
failed the identity clause failed because the **prompted** arm degenerated, which is a reason to look harder
at the prompt surface rather than a reason to keep the list.

**Carried forward.** The real-machine CLI E2E stays deferred by the operator and is the next iteration's
first work (see `## Roadmap Position`). The P8 clause that could not see a 5 289-character cue is recorded
in the results guide §6 and belongs to a protocol revision, not to a quiet patch.
