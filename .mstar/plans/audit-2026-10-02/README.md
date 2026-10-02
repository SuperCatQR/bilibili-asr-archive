# Audit Report — bilibili-asr-archive @ ff39fd0 (2026-10-02)

Read-only codebase audit (`/codebase-audit`, full-audit variant, `standard` effort). Executor: `@code-reviewer`
(Mode B). Base commit `ff39fd0`. Fan-out: 9 read-only category seats via the dsh native `workflow` tool
(`meta.name: mstar-audit-fanout`). The `migration` / `dx` / `docs` / `direction` seat results were truncated by
the runner and are recorded as **uncollected** in Coverage below — their categories were re-covered by direct
reads where a finding already existed in the residual register; no new dx/docs/direction finding is claimed
from this run.

This report is **advisory** — plan candidates for the normal Prepare → Execute flow. It does not enter the
per-plan state machine. 56 residuals were already open in `.mstar/projects/_default/residuals.json` at audit
time (1 high, 24 medium, 31 low); this index cross-references them and does **not** re-plan them.

## Findings

| # | Finding | Category | Impact | Effort | Risk | Confidence | Evidence |
|---|---------|----------|--------|--------|------|------------|----------|
| 1 | Make the second hotword pass re-decode from a clean model/cache state (shared helper) | bug | The two-pass hotword contract assumes pass 2 re-decodes with the re-seeded prompt; nothing between the two `transcribe()` calls busts the runner/model cache, so a caching runner can serve pass 2 from pass 1's state and a kept token stays unapplied — the archived text differs silently from what the operator believes the contract produced. | M | MED | MED | `src/bili_asr/coordinator.py:596-603`; `src/bili_asr/cli/asr.py:216-227`; `src/bili_asr/asr.py:1084-1086` |
| 2 | Apply `--limit` once on the store-sourced `asr` queue | bug | `--limit N` is applied twice on the default store route (store-side `LIMIT ?`, then a CLI re-slice); today a no-op, but a live trap — any future per-bvid/over-fetch store limit turns the CLI slice into a silent row-drop, and the two queue routes disagree on who owns the bound. | XS | LOW | HIGH | `src/bili_asr/cli/asr.py:99-105`; `src/bili_asr/storage/database.py:1855-1857`; `src/bili_asr/cli/_shared.py:210` |
| 3 | Batch manifest ledger writes (ManifestStore.upsert re-reads + rewrites whole JSONL per row) | perf | `upsert()` re-reads the entire manifest under the lock on every call (~14 prod sites; ~3 per ASR row). Batch shape is O(rows × manifest bytes); on the documented 1730-video corpus every archived row costs a full ~1700-record parse + flock + fsync. Dominates large-batch wall time and serializes all completions on one lock. | M | MED | HIGH | `src/bili_asr/manifest.py:265-296`; call sites `coordinator.py:526,952,960`, `cli/asr.py:242`, `cli/pilot.py:198,309,568`, `cli/publish.py:190`, `cli/queue.py:107,375`, `cli/_shared.py:105` |
| 4 | Pace all three per-row metadata getters (detail / parts / tags) behind one gateway decorator | perf | Full-corpus `fetch-meta` fires ~90 sequential unpaced RTTs per 30-row page with zero delay — the exact load pattern that trips Bilibili's 412 risk-control and terminates the whole enumeration mid-run. Only the tag leg is registered (M-R1); the identical detail/parts legs are not. | M | MED | HIGH | `src/bili_asr/services/metadata_ingest.py:336-375`; `src/bili_asr/sources/bilibili_api_gateway.py:722-841` |
| 5 | Skip already-stamped parts before the filesystem probe in `search-index` build | perf | Every build re-stats and re-reads up to 84×3 markdown files whose block_keys are already stamped; on the audio-only root (R14) the candidate set is the whole corpus every build — hundreds of filesystem probes + full md reads even when zero new transcripts exist. Build time scales with corpus size. | S | LOW | HIGH | `src/bili_asr/search_index.py:1392-1412` |
| 6 | Trust the in-memory attempt-count map instead of re-scanning attempts.jsonl per record | perf | `AttemptLedger.append` re-reads and re-parses the whole append-only sidecar to compute the next attempt number; after N attempts the run has done O(N²) parses (~5 records/row → thousands of full-file scans in a 1000-row campaign). | S | LOW | HIGH | `src/bili_asr/coordinator.py:209-225`; `_attempt_counts` at `:354-361` |
| 7 | Fix conftest `sys.path` hacks + `tmp_root` PID-reuse flake (test-infra hardening) | tests | The suite silently tests a sys.path-loaded tree (not the installed artifact) and every fixture pays hand-rolled mkdir/rmtree; `tmp_root` raises FileExistsError on PID reuse, a recorded source of random full-suite reds (conftest forensics hook). | M | MED | HIGH | `tests/conftest.py:15,20,125-138`; `tests/test_audio_budget.py:111` |
| 8 | Register pytest markers + centralize the live/scale opt-in gates | tests | 35 live/smoke/scale tests across 4 files are invisible to collection metadata (no `-m`, no CI gate); env-var names can drift; the per-file hand-rolled skip idiom is repeated. | XS | LOW | HIGH | `tests/test_live_*_smoke.py`, `tests/test_persistence_scale.py:38`; `pyproject.toml:78-80` |
| 9 | Consolidate the three cue-parsers into one transcripts module | tech-debt | Three modules parse the same two artefact shapes with independent logic; `quality._read_cues` accepts any parseable JSON while `proofread` guards `source == "asr"` — the exact divergence residual C-R3 names. Consolidation is a precondition for closing C-R3 cleanly. | M | MED | MED | `src/bili_asr/quality.py:645-708`; `src/bili_asr/proofread.py:485-528`; `src/bili_asr/asr.py:1337-1347` |
| 10 | Deduplicate the shared constant/helper clusters (terminal statuses, utc_now_iso, dead cli/meta.py copies, _now, canonical stem, hotword two-pass) | tech-debt | The same facts are hand-maintained in 3-4 places each: 4× `frozenset({"archived","gone"})`; 2× `utc_now_iso` + a re-export wrapper; byte-identical dead `_run_error_codes`/`_format_run_line` in `cli/meta.py`; 2× `_now`; 3× `_canonical_stem`; the hotword two-pass orchestration duplicated verbatim. Drift is invisible until a pair disagrees. | M | MED | HIGH | `coverage_report.py:20`, `scheduler.py:32`, `coordinator.py:45`, `campaign.py:35`; `meta_cursor.py:49`, `run_ledger.py:79`, `coordinator.py:99`; `cli/meta.py:148,170`; `metadata_ingest.py:61`, `subtitle_ingest.py:74`; `quality.py:369`, `integrity.py:643`, `coordinator.py:969`; `cli/asr.py:203-229`, `coordinator.py:580-603` |

Impact is prose — what goes wrong and who pays — never a numeric label.

## Direction (separate)

Direction category seat was **uncollected** (runner truncation); no grounded new direction claim is made this
run. The strongest repo-evidence pointers for the maintainer (to be developed in a future `next`/`roadmap`
pass, not planned now):

- **The store↔chain bridge is the live seam.** Residual R14 (high: ASR stage writes a bundle but no
  `transcripts` row, so `v_missing_transcript` never converges) plus R13/R15 (the store route cannot express
  "meta_ok, go harvest" through `pilot`/`schedule`) all point at one architectural fact: two queue truths
  (manifest SSOT vs `archive.db`) are bridged ad hoc. A direction plan that makes the store the single queue
  authority — or explicitly rules it out — would retire a whole residual family at once.
- **Two-pass hotword re-seeding is unmeasured under the new engine.** The governance ruling left the built-in
  list empty pending a per-token keep/drop re-measurement (README §"corpus vocabulary"); every quoted figure is
  FunASR-era. Re-measuring under Qwen3-ASR — with insertions counted separately from recoveries — is recorded
  work that gates whether the two-pass path (plan 001) is worth keeping.

## Coverage

| # | Unit (surface × boundary/invariant × subsystem × category) | Status | Evidence / check | Reason / gap |
|---|-------------------------------------------------------------|--------|------------------|--------------|
| C1 | ASR two-pass hotword × pass-2 cache-state invalidation × coordinator/cli × bug | covered | `coordinator.py:596-603`, `cli/asr.py:216-227`, `asr.py:1084-1086` opened; no cache-busting boundary between the two `transcribe()` calls | — |
| C2 | store-route `--limit` × single-application × cli/asr × bug | covered | `cli/asr.py:99-105`, `database.py:1855-1857`, `_shared.py:210`, `queue.py:278,330` opened; confirmed double application | — |
| C3 | manifest ledger × per-row full re-read under lock × manifest × perf | covered | `manifest.py:265-296`, `194-231` opened; `upsert()` re-reads whole JSONL per call | — |
| C4 | metadata per-row getters × inter-call pacing × services × perf | covered | `metadata_ingest.py:336-375`, `bilibili_api_gateway.py:722-841` opened; no pacing primitive | — |
| C5 | search-index build × skip-already-indexed-before-fs-probe × search_index × perf | covered | `search_index.py:1392-1412` opened; `stamped_part_ids` check precedes only the text read, not the candidate materialization | — |
| C6 | attempt ledger × next-attempt numbering without full-file rescan × coordinator × perf | covered | `coordinator.py:209-225`, `_attempt_counts` `:354-361` opened; `append` re-scans | — |
| C7 | conftest sys.path + tmp_root × PID-reuse / installed-artifact fidelity × tests × tests | covered | `conftest.py:15,20,125-138`, `test_audio_budget.py:111` opened | — |
| C8 | live/scale opt-in gates × collection metadata / marker registry × tests × tests | covered | 4 smoke/scale files + `pyproject.toml:78-80` opened; no markers registered | — |
| C9 | cue parsing × single shared reader × quality/proofread/asr × tech-debt | covered | `quality.py:645-708`, `proofread.py:485-528`, `asr.py:1337-1347` opened; 3 independent parsers, divergent source-guard | — |
| C10 | duplicated constants/helpers × single-source-of-truth × 6 clusters × tech-debt | covered | 6 clusters grep + opened (`coverage_report.py:20`, `scheduler.py:32`, `coordinator.py:45`, `campaign.py:35`, `meta_cursor.py:49`, `run_ledger.py:79`, `coordinator.py:99`, `cli/meta.py:148,170`, `metadata_ingest.py:61`, `subtitle_ingest.py:74`, `quality.py:369`, `integrity.py:643`, `coordinator.py:969`, `cli/asr.py:203-229`, `coordinator.py:580-603`) | — |
| C11 | TLS posture of pinned `bilibili-api-python==17.4.2` httpx client × certificate verification × sources × security | blocked | `bilibili_api_gateway.py:972,1021` (`verify=False` into package Api) opened; httpx client default unverifiable statically | Requires runtime/MITM probe on the pinned package (per `security-review.md`); parked as a Needs-verification lead, no plan |
| C12 | WBI signing-key seeding × per-process randomness mix-in × bili_client × security | blocked | `bili_client.py:390-404`, `53-70` opened; key derivation accepts the live nav response | Reachability needs an on-path/MITM position; LOW-confidence lead, runtime verification required, no plan |
| C13 | fetch-meta page loop × unbounded walk on cursor corruption × services × bug | deferred | prior evidence: residual R9 (`metadata_ingest.py:417` rewind) + M-R12 (`page.total` not a row count) | LOW-confidence new lead; distinct from registered R9/M-R12 but only bites on a corrupted cursor; recorded here, no plan until the store-route cursor handling is next touched |
| C14 | manifest multi-process upsert × last-write-wins on concurrent CLI × manifest × bug | deferred | prior evidence: `coordinator._run_batch_owned` holds `archive_writer` per batch (`coordinator.py:837`); the attack refuted the coordinator path, leaving only the unguarded concurrent-CLI-wrap variant | Out-of-contract concurrent invocation (project is `sequential-no-daemon` by design); if the project rules concurrent CLI out of scope, close as by-design |
| C15 | metadata hot-path × bounded perf regression guard × tests × tests | deferred | prior evidence: `test_persistence_scale.py:38` is the only (100 s, opt-in) scale probe; O-R3 search N+1 + C-R1 sidecar 8.55x already registered | A bounded query-count test is a rider on the perf fixes, not a standalone plan this run |
| C16 | test_harness_state live-register coupling × exact-zero ceiling now landed × tests × tests | not_applicable | `test_harness_state.py:86-94` opened; `REGISTER_VIOLATION_CEILING = 0` — Task 2 of `20260928-harness-state-contract` has landed and the guard is exact | The seat's "codifies 144 as green" claim is stale; no live defect, no plan |
| C17 | metadata ingest tag/detail/parts × shape-resilience / FK / cache residuals × services × tech-debt | deferred | register: M-R1..M-R12 already track pacing (partially superseded by finding 4), shape error, FK raise, cache bounds, rerun test | Already registered; only the unregistered detail/parts pacing legs are planned (finding 4) |
| C18 | archive.db schema version stamp × user_version pragma × storage × tech-debt | deferred | `database.py:160-177`, `search_index.py:1130-1133` (no-migration rule) noted | Cosmetic against the structural column-presence guard; MED-confidence, low value — recorded, no plan |
| C19 | cli/run.py split × _cmd_run / _cmd_schedule separation × cli × tech-debt | deferred | `cli/run.py:289,412` noted; direction already tracked by residual O-R7 (commands/ package extraction) | A specific split of one file inside a larger O-R7-owned extraction; fold into O-R7 rather than a standalone plan |
| C20 | migration / dx / docs / direction categories × (four seats) × — × — | uncollected | — | Seat results truncated by the workflow runner; these four categories were not independently re-audited this run. dx/docs/direction had no open residual forcing a plan; no new finding is claimed. |

Coverage is partial. Not examined: the four truncated category seats (migration / dx / docs / direction) beyond
cross-referencing the existing residual register; `.venv/`, `docs/archive/`, `verification-results/`,
`notes/video-inventory/` (data/archival, skipped per recon). Uncollected: migration, dx, docs, direction.
Unresolved: the two security leads (C11 TLS posture, C12 WBI seeding) are runtime-dependent and remain
Needs-verification leads, not findings. One prior audit directory exists
(`.mstar/plans/audit-2026-09-26/`) but its README is absent from disk; its plan bodies were not carried into
this run's index, so no prior `covered`/`deferred` reconciliation was possible against it.

## Needs verification

- TLS certificate verification default in the pinned `bilibili-api-python==17.4.2` httpx client — verify with a
  MITM test double or by inspecting the pinned httpx client defaults in the lockfile closure
  (`uv.lock` resolves httpx transitively; `src/bili_asr/sources/bilibili_api_gateway.py:972,1021` passes
  `verify=False`). If off by default, every SESSDATA-authenticated request is exposed on a hostile network.
- Whether the two-pass hotword re-decode actually re-decodes — verify on the pinned `transformers>=5.13`
  whether the model's dynamic prefix cache survives across two `generate()` calls on the same features
  (`src/bili_asr/asr.py:1084-1086` passes no cache-control argument). Plan 001 carries a stub-model test; a
  real-model confirmation is the operator-side check.

## Hardening & checked notes

- Checked and clean: SQL is fully parameterized; the only f-string interpolation sites are module constants or
  allowlist-validated identifiers (`search_index.py:1116-1124` tokenizer from a fixed probe tuple;
  `database.py:1837` view name from `_VIEW_BY_GAP` allowlist). No `shell=True`, no `eval`/`exec`, no
  `pickle`/`yaml.load`; both ffmpeg call sites use argv lists with descriptor hygiene (`audio.py:71-84`,
  `asr.py:546-571`).
- Checked and clean: path confinement is uniformly descriptor + `O_NOFOLLOW` (`path_policy.py`,
  `integrity.py:119-147`, `archive.py:85-160`, `artifact_root.py:224-269`).
- Checked and clean: SESSDATA is resolved via flag/env only, redacted on all display paths, and scrubbed from
  exports/searches; no committed secret found by pattern scan of tracked files (placeholder hits only).
- Hardening: the local `requests` transport verifies TLS by default
  (`src/bili_asr/bili_client.py:172-215`); the residual risk is concentrated in the pinned package's own
  httpx client (see Needs verification), not the local transport.
- By-design (not findings): `sequential-no-daemon` concurrency (D12); ffmpeg as a system dependency; archive.db
  rebuildable-by-policy with no in-place migration; torch deliberately omitted from the `[asr]` extra (ROCm
  recipe); honoring `BILI_HTTP_PROXY` / `HTTPS_PROXY`; SESSDATA as an API-cookie-only credential.

## Execution order & status

| Plan | Title | Priority | Effort | Depends on | Status |
|------|-------|----------|--------|------------|--------|
| 001  | Second hotword pass re-decodes from clean state | P1 | M | — | TODO |
| 002  | Apply `--limit` once on the store-sourced `asr` queue | P2 | XS | — | TODO |
| 003  | Batch manifest ledger writes | P1 | M | — | TODO |
| 004  | Pace the three per-row metadata getters | P2 | M | — | TODO |
| 005  | Skip already-stamped parts in `search-index` build | P3 | S | — | TODO |
| 006  | Trust the in-memory attempt-count map | P3 | S | — | TODO |
| 007  | Fix conftest sys.path + tmp_root PID-reuse flake | P2 | M | — | TODO |
| 008  | Register pytest markers + centralize opt-in gates | P3 | XS | 007 | TODO |
| 009  | Consolidate the three cue-parsers | P2 | M | — | TODO |
| 010  | Deduplicate the shared constant/helper clusters | P3 | M | — | TODO |

**Dependency ordering.**

- **007 → 008**: 008 touches `tests/conftest.py` and the smoke/scale files; 007 rewrites the same conftest
  fixture block. Land 007 first so 008 edits the already-hardened fixture.
- **001 ↔ 010 (partial)**: 010's hotword two-pass dedup and 001's shared-helper extraction target the same two
  call sites (`cli/asr.py:203-229`, `coordinator.py:580-603`). Land them together or in 001 → 010 order to
  avoid a rebase; 001 owns the correctness change (cache busting), 010 owns the mechanical dedup.
- **004** is the unregistered legs of residual M-R1; coordinate with that register entry so the tag leg is not
  double-planned.
- **009** is the structural precondition for residual C-R3 (silent-pass sibling readers); it does not close
  C-R3 by itself.
- None of these plans may start with real-hardware / live-network verification (development-AC boundary); the
  two Needs-verification leads above are operator/runtime checks, not plan gates.

## Findings considered and rejected

- **test_harness_state codifies the 144-violation register as green** — not worth doing because the seat's
  premise is stale: `tests/test_harness_state.py:86-94` now pins `REGISTER_VIOLATION_CEILING = 0` (Task 2 of
  `20260928-harness-state-contract` has landed and the guard is exact). No live defect.
- **cli/run.py split into `_cmd_run`/`_cmd_schedule`** — not a standalone plan; the commands/ package
  extraction direction is already tracked by residual O-R7. Fold the specific split into O-R7's owning plan.
- **archive.db `user_version` schema stamp** — not worth doing now; cosmetic against the robust structural
  column-presence guard and the documented no-migration rule. Recorded as a deferred lead only.
- **fetch-meta unbounded page walk on cursor corruption** — not planned; only bites on a corrupted cursor (an
  already-registered R9/M-R12 surface), LOW confidence, and the normal empty-page exit bounds the real case.
- **manifest multi-process last-write-wins** — rejected for the coordinator path (it holds `archive_writer`
  per batch); survives only as an out-of-contract concurrent-CLI-wrap lead. If the project rules concurrent
  CLI invocations out of scope (consistent with `sequential-no-daemon`), close as by-design.
- **metadata ingest shape-resilience / FK / cache residuals (M-R1..M-R12)** — already registered; not
  re-planned. Only the unregistered detail/parts pacing legs are planned (finding 4).
- **proofread parses the full multi-MB raw sidecar per invocation** — not planned; proofread is per-part
  interactive (human-paced), so the parse cost is bounded. Cross-referenced to residual C-R1 (sidecar size)
  rather than re-planned.

## Red-team dispositions

- Finding 1 (second-pass cache carry-over): **survived** the counter-example/simpler-explanation/evidence
  pass — the cited code shows no cache-busting boundary and the correctness implication is distinct from the
  registered O-R1 (which records only the duplication, not the cache risk). Confidence stays MED pending a
  real-model confirmation (see Needs verification).
- Finding 3 (manifest per-row full re-read): **survived** — the cited `upsert()` re-read is present at
  `manifest.py:280` and the ~14 call sites are grep-confirmed.
- "ManifestStore last-write-wins loses concurrent upserts": **refuted** for the coordinator path (the attack
  itself confirmed `run_batch` holds `archive_writer` and re-reads per row); kept only as the LOW out-of-contract
  CLI-wrap lead, which is recorded under considered-and-rejected, not as a finding.
- "`_partial_run_state` lexicographic timestamp comparison is unsound": **refuted** — confirmed sound under the
  single-writer UTC-ISO Z-suffixed form shared by `run_ledger.utc_now_iso` and `coordinator._utc_now_iso`.
- "hotword guard can admit a token the audio never spoke": **refuted as a new finding** — this is the already-
  registered `20260922-proofread-wave · R1` mechanism (documented substring semantics, by design); excluded.
- Security leads (TLS posture, WBI seeding): **uncovered-kept** as Needs-verification leads — the attack could
  not reach a runtime-dependent claim statically; they are not promoted to findings and get no plan.
