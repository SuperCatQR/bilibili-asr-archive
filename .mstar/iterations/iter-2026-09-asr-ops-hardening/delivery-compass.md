---
iteration_id: iter-2026-09-asr-ops-hardening
title: "ASR operational hardening: truthful GPU enablement, batch model reuse, unified quality signals, declared provenance identity"
status: locked
start_date: 2026-09-12
iteration_base_branch: main
spec_integration_branch: iteration/iter-2026-09-asr-ops-hardening
target_branch: main
effort_scale: L
plans:
  - 20260912-gpu-enablement-truth
  - 20260912-batch-model-reuse
  - 20260912-quality-signal-merge
  - 20260912-asr-provenance-identity
---

# iter-2026-09-asr-ops-hardening Delivery Compass

## Scope

Spec points locked by this iteration. Each reverses out a defect measured in the 2026-09-12
ten-video GPU run, not taste: all five are **retained**, each traceable to a measurement
recorded in `guides/2026-09-12-ten-video-audit.md`, so none was killed or merged, and none was
added that the measurement does not carry. Every point states its `Evidence:` anchor below;
the full traceability table (point → measurement → repository check) is in
`guides/scope-rationale.md`.

1. **Truthful GPU enablement.** `README.md` (L20–24) publishes "AMD 7800XT GPU with ROCm 5.7+
   drivers" and `pip install torch --index-url https://download.pytorch.org/whl/rocm6.0`, and
   `asr.py` (L320–322) repeats that command in its runtime error hint. On the operator's
   WSL2 + RX 7800 XT target that path does **not** produce a working device: the PyTorch.org
   ROCm wheel aborts inside torch's bundled `librocprofiler-sdk` (`Found 0 rocprofiler agents
   and 2 HSA agents`), which AMD documents as unsupported on WSL. The verified path is:
   ROCm 7.2.1 runtime + `librocdxg` (ROCDXG), the **repo.radeon.com** torch wheel, the ROCm
   userspace libraries, `/opt/rocm-<ver>/lib` on the loader path, the WSL-compatible
   `libhsa-runtime64.so` in the venv, and `HSA_ENABLE_DXG_DETECTION=1`. The repository must
   publish the verified recipe and a runtime self-check instead of the broken one.
   `Evidence:` guide §4.1 L78–93 — ROCm 5.7 carries no `gfx1101` support at all (L84); the
   PyTorch.org wheel imports with `torch.cuda.is_available()` `False` and aborts under
   `HSA_ENABLE_DXG_DETECTION=1` (L85–87); the ROCm 7.2.1 + ROCDXG + repo.radeon.com recipe is
   the one that showed the device (`gfx1101`, 15.8 GB, matmul on device, L88–93).
2. **Batch model reuse must be reachable and stated.** The run-scoped reuse contract is
   already designed and implemented for the coordinator path
   (`{KNOWLEDGE_DIR}/architecture-patterns/run-scoped-asr-provenance.md`), but the
   obvious per-item `bili-asr asr --bvid …` loop silently forfeits it: the ten-video run
   spent ~5.6 min of 21.8 min (26 %) reconstructing the model. The iteration makes the
   reuse path the documented one and gives the operator evidence that reuse happened.
   `Evidence:` guide §4.2 L95–101 — coordinator reuse at `coordinator.py:494`
   (`if self.asr_runner is None:`), and the ten-video wall-clock decomposition 21.8 min =
   ≈ 16.3 min decode + ≈ 5.6 min per-item overhead (26 %), measured on 2026-09-12.
3. **One quality surface.** Artifact-shape quality lives in `src/bili_asr/quality.py`
   (`coverage --quality`, reason codes `empty`/`malformed`/`non_monotonic`/`overlap`/
   `out_of_range`/`identity_mismatch`/`artifact_missing`); the model-confidence and
   content-anomaly signals added on 2026-09-12 live in a parallel `scripts/asr_quality.py`.
   Two entry points for one question is the defect; the content signals move into the
   existing reason vocabulary and the parallel script retires.
   `Evidence:` guide §4.3 L103–109 — the shape-layer vocabulary as shipped in
   `src/bili_asr/quality.py` L15–22, and the existing `scripts/asr_quality.py`
   (confidence, fragments, over-long cues, repeated n-grams, cross-system agreement) that
   the coverage surface knows nothing about.
4. **Declared producer identity in provenance.** Every archived row of the ten-video run
   records `asr_model_name: "[redacted]"`, because a local checkpoint path cannot be a
   redaction-safe identifier. Redaction is deliberate and stays; what is missing is the
   *declared* hub-level identity, so an archive can still answer "which model produced
   this" without serializing a path.
   `Evidence:` guide §4.4 L111–115 — all ten archived files record `[redacted]`; the
   redaction rule itself is `src/bili_asr/asr.py` L405–412 and the frontmatter write is
   `src/bili_asr/archive.py` L321.
5. **ASR observability for the two blind spots.** The run cannot answer (a) how much
   audio the VAD actually captured (1–15 gaps > 3 s per video, unresolvable between
   speaker pauses and VAD misses) or (b) where the low-confidence cues are. Both become
   recorded facts rather than inference.
   `Evidence:` guide §3 L68–74 — 1–15 gaps > 3 s per video (`BV1147c6sEKs` 15,
   `BV1eiPczHEqg` 15) with nothing recording VAD capture, and `asr_low_confidence_cues`
   naming a count without a location while per-cue confidence lives only in `raw.json`;
   the 11 low-confidence cues (conf ≤ 0.4) and their composition are guide §2 L61–63.

Both halves of point 5 stay in one point on purpose: they were measured in the same run,
and the same record surface (the transcript's provenance + frontmatter) is what answers
both.

## Plans

| plan_id | Name | Status | Notes |
|---------|------|--------|-------|
| 20260912-gpu-enablement-truth | Verified GPU enablement: docs, runtime hint, environment self-check | Done | Spec point 1; merge `5ee7832` |
| 20260912-batch-model-reuse | Batch model-reuse contract on the documented path | Done | Spec point 2; merge `27ac740` |
| 20260912-quality-signal-merge | Content-quality reasons folded into the existing quality surface | Done | Spec point 3; merge `6ab1ad2` |
| 20260912-asr-provenance-identity | Declared model identity + VAD capture and low-confidence locations in provenance | Done | Spec points 4–5 |

Status values: `Todo` | `InProgress` | `InReview` | `Done` | `Blocked`

## Milestones

| Milestone | Target date | Status |
|-----------|-------------|--------|
| Spec freeze (compass `locked`) | 2026-09-12 | pending |
| Dev complete | 2026-09-12 | pending |
| QC complete | 2026-09-12 | pending |
| Iteration close | 2026-09-12 | pending |

## Acceptance Criteria

Every criterion is falsifiable by a named command, test, or archived field — not by a
transcript of a good run. `Check` names the surface a reviewer runs or reads; `Spec` /
`Plan` tie it back to the Scope point and the plan that owns it (`P1` = `20260912-gpu-enablement-truth`,
`P2` = `20260912-batch-model-reuse`, `P3` = `20260912-quality-signal-merge`,
`P4` = `20260912-asr-provenance-identity`).

| # | Acceptance criterion | Check (command / test / archived field) | Spec | Plan |
|---|----------------------|----------------------------------------|------|------|
| A1 | On the WSL2 + RX 7800 XT target the environment self-check `scripts/check_asr_env.py` named in `README.md` exits `0` **iff** the three verified invariants hold together: (i) the device is visible — `torch.cuda.is_available()` is `True` and the check names the device it used (`gfx1101`); (ii) an archive produced on that host records `asr_device: "cuda"` in the transcript frontmatter; (iii) the check exits non-zero, printing the verified remediation, on a host with no working device. The check is the only entry point named for this question, and no document or error string still recommends the PyTorch.org ROCm wheel for WSL. | Run `python3.12 scripts/check_asr_env.py` on the target and read its exit code; set `ARCHIVE=<archive-root>` on its own line, then `grep -n '^asr_device:' "$ARCHIVE"/transcripts/md/*.md` (a command-prefix assignment is not visible to its own expansions; `<archive-root>` is the root passed to `--archive-root`; the unquoted glob over `transcripts/md/*.md` is required because the bundle is named `{pubdate}_{bvid}.p{page}_<title>.md`, so there is no `<work_id>.md` to open — same form as `README.md`); `grep -rn 'download.pytorch.org/whl/rocm' README.md src/ docs/` returns nothing; `tests/test_asr_reproducibility.py::test_cuda_unavailable_raises_dependency_error_with_rocm_hint` (today L330–351) asserts the hint carries the verified recipe tokens instead of the broken URL | 1 | P1 |
| A2 | The documented batch path constructs the model **once** for a ≥ 3-item batch, the run's own output states that construction count, and `README.md` states that a per-item `bili-asr asr --bvid <bvid>` loop forfeits the reuse. | A test asserting model-construction count `== 1` for a ≥ 3-item run through the documented path, extending the construction-counting fixture already used by `tests/test_asr_reproducibility.py::test_fixture_benchmark_reports_only_construction_and_shape` (L312) and the reuse oracle `::test_target_runner_reuse_oracle_is_target_facing` (L186); one printed line per batch carrying the count (printed whenever a construction was paid **or** ASR items ran, so a batch that failed every transcription still states its cost); README statement greppable | 2 | P2 |
| A3 | `bili-asr coverage --quality --archive-root <root>` answers the whole question from one surface: every reference-free signal `scripts/asr_quality.py` reports today (low-confidence cues, fragment cues, over-long cues, repeated n-grams) is reported on an existing archive as a reason in the existing vocabulary, and the reference-agreement signal is reported when a second transcript is supplied. The shape-layer reasons keep their current codes and output shape, and the parallel script is gone. | Run the command on an existing archive root that holds ASR transcripts (the 2026-09-12 run's output root, or a fresh single-item run); signal list compared against `git show <iteration-base>:scripts/asr_quality.py`; new reasons appear in `src/bili_asr/quality.py` `REASON_CODES` (L15–22); `tests/test_quality.py` + `tests/test_coverage_report.py` pass with their assertions unmodified; `git ls-files scripts/asr_quality.py tests/test_asr_quality_script.py` is empty | 3 | P3 |
| A4 | An archive produced from a **local checkpoint directory** records the declared producer identity when the operator declares it — `asr_model_name` carries the hub id (e.g. `FunAudioLLM/Fun-ASR-Nano-2512`) and `asr_model_revision` the declared revision — while the local path is still never serialized; with no declaration `asr_model_name` keeps the configured id only when that id is itself redaction-safe, and is `[redacted]` otherwise. No frontmatter value, raw sidecar, or CLI output carries a filesystem path, URL, or credential-like value. | Reproduce from `README.md` alone (declaration surface documented there), then read the archived frontmatter fields; `tests/test_asr_reproducibility.py::test_provenance_preserves_safe_slash_qualified_model_identifier` (L250) and `::test_provenance_redacts_path_url_and_credential_like_model_values` (L265) stay green and cover the declared-identity case; forbidden-token scan over frontmatter + `raw.json` | 4 | P4 |
| A5 | Every ASR transcript records how much audio the VAD captured and **where** the low-confidence cues are: frontmatter keys following the existing `asr_` prefix convention carry the VAD segment count, captured seconds, and captured ratio (captured/total, in `[0, 1]`), and the low-confidence cue locations as their start seconds — with the existing `asr_low_confidence_cues` count consistent with that location list. | Read the archived frontmatter keys (named `asr_vad_segments`, `asr_vad_captured_s`, `asr_vad_captured_ratio`, `asr_low_confidence_at`; renamed only by amending this compass) and recompute both from `raw.json` segments; a test pins key presence, the ratio bound, and count-vs-list consistency | 5 | P4 |
| A6 | Transcript text is unchanged by this iteration: the recorded 2037-token cue fixture renders identically, its assertions are not loosened, and the suite is green. | `python -m pytest -q`; `python -m pytest -q tests/test_asr_cues.py` over `tests/fixtures/asr-cues/BV1wLTP6NE9h.p0.tokens.json` (2037 tokens, `tests/test_asr_cues.py` L3–6) passes at the iteration base and at head; `git diff --stat <base>..HEAD -- tests/test_asr_cues.py tests/fixtures/asr-cues/` is empty | all (guard) | P1–P4 |

Explicitly **not** claimed by this iteration:

- Any accuracy, content-quality, or hotword improvement — the operator judged current
  transcription quality sufficient on 2026-09-12 (see Non-Goals and guide §2 L36).
- Any throughput benchmark or speed-up number for the batch path: A2 claims one model
  construction, not a measured wall-clock gain.
- Corpus coverage: the ten-video run is 125 min of the visible corpus (guide §1 L9–26),
  and nothing here claims more.
- Automatic ROCm installation or device auto-detection: this iteration documents and
  diagnoses the environment, it does not install or probe for it.

## Non-Goals

Content quality is explicitly **out** of this iteration: the operator's 2026-09-12 decision
was that current transcription quality is sufficient, so the audit's content findings are
recorded as evidence and are not scheduled work (guide §2 L36–63; the guide itself labels
them "recorded as evidence, not scheduled work"). Nothing here re-tunes accuracy, replaces
the model, expands the hotword list, changes ITN policy, or introduces a human-adjudicated
gold standard; the audit's own metric caveat (guide §2 L65–66) stays attached to those
findings.

Behaviours that are already designed stay non-goals — they are named here so no plan
re-opens them as defects:

- Accuracy re-tuning, model replacement, hotword-list expansion (the corpus list already
  ships), ITN policy changes. Content errors found by the audit (English term
  fragmentation, the `六万`/`60000` inconsistency) are evidence, not work items.
- Cue-shaping rules. The pinned single cue pass is a fixed input to this iteration; A6
  exists to prove it did not move, not to improve it.
- Audio retention policy. `BILI_KEEP_AUDIO=1` and `docs/audio-retention-policy.md` already
  exist and already state the three costs (L5–9); the run's re-download need was
  self-inflicted (guide §5 L117–121).
- Manifest compaction. Append-oriented revisions with derived latest-valid state are
  decided design (`operational-sidecars.md` guidance 10, L105), not drift; guide §5
  L122–124.
- Residual R1 (gateway import surface, `20260911-subtitle-gateway`) — it stays open in
  `{PROJECT_DIR}/_default/residuals.json` for the next plan whose file list includes
  `src/bili_asr/sources/bilibili_api_gateway.py`; no plan in this iteration does, so this
  iteration does not close it.
- CPU-vs-GPU throughput benchmarking, and automatic ROCm installation / device
  auto-detection (both already non-goals from `iter-2026-09-funasr-nano-7800xt`, L36–37).
  This iteration documents and diagnoses the environment; it does not install it.

## Roadmap Position

- **Current iteration（iter-2026-09-asr-ops-hardening）**：turns the 2026-09-12 ten-video
  GPU run's measured defects into documented, testable behaviour: truthful GPU enablement
  (A1), reachable model reuse (A2), a single quality surface (A3), declared provenance
  identity (A4), and the two observability facts the run could not answer (A5) — with the
  cue text held still as the guard (A6). Its evidence base is
  `guides/2026-09-12-ten-video-audit.md`; the ten videos are the shortest parts of the
  visible corpus (449 s–1115 s, 125 min of audio, guide §1 L9–26), so this iteration
  hardens the path on the cheap end before the corpus run resumes.
- **Next iteration**：carry the inherited medium residual R1 — `scripts/verify_baseline.py`'s staged tree still
  cannot collect `tests/test_check_asr_env.py` (`rc=2`, zero tests collected), so the documented baseline gate
  aborts; the fix is ~2 lines in that file, which no plan in this iteration owns (plan-QC seats 1/2, 2026-09-13).
  Then resume corpus acquisition at scale — the 63 visible parts,
  449 s–9151 s (≈ 93 h of audio) — with the hardened ASR path and the SQLite
  audio/sidecar work. Source for the corpus figures: `guides/scope-rationale.md` §3
  (the live archive's `video_parts`: 63 rows, min 449 s, max 9151 s). Trigger: this
  iteration's Phase 5 merge-ready exit. Owner: `@project-manager`.
- **最终目标**：an unattended, resumable archive of the whole visible corpus whose every
  transcript states what produced it, how much audio it covers, and how confident it is —
  runnable by the operator on either box without re-deriving the environment.

## Delivery Branch Policy

> Mirror of frontmatter; keep in sync with workflow snapshot `{WORKFLOW_DIR}/<id>/snapshot.json` `branch` anchors.

| Field | Value |
|-------|-------|
| `iteration_base_branch` | `main` |
| `spec_integration_branch` | `iteration/iter-2026-09-asr-ops-hardening` |
| `target_branch` | `main` |

Rationale: identical to the last three completed iterations
(`iter-2026-09-subtitle-transcript-sqlite`, `iter-2026-09-funasr-nano-7800xt`,
`iter-2026-09-bilibili-api-sqlite`) — `main` is the live line, each iteration integrates on
`iteration/<id>` and returns to `main`. Repository policy is `push no-pr`.

## Risk Register

Only risks whose mitigation a plan can actually execute are kept; each mitigation names the
criterion it defends.

| Risk | Likelihood | Impact | Mitigation (plan-executable) |
|------|-----------|--------|------------|
| The verified GPU recipe is environment-specific (driver/ROCm pairing) and rots | Med | Med | Publish it as a *checked* recipe, not a command list: the self-check of A1 re-verifies the invariants at run time (device visible, ROCm loader path, DXG detection) and its failure output is the remediation text A1 requires — so a rotted recipe fails loudly on the host instead of in the docs |
| Folding content reasons into `quality.py` changes an existing command's output contract | Med | Med | Extend the reason vocabulary additively and keep the seven existing codes and the output shape byte-compatible: `tests/test_quality.py` and `tests/test_coverage_report.py` must pass with their assertions unmodified (A3), with the new reasons covered by focused tests |
| Batch-reuse work drifts into a new CLI surface the project does not need | Med | Low | Prefer the documented coordinator path; add a multi-item entry point only if P2's clarify step records that the documented path is unreachable for the operator's flow. Otherwise A2 is met on the existing path by documentation plus the printed construction count — no new command |
| Recorded-token fixture over-fits the current cue rules and hides a regression | Low | Med | Keep the fixture assertions on the hard invariants (text reassembly, no fragments, no leading marks) rather than a frozen cue list, and require the assertions to be unmodified across the iteration (A6) so a regression cannot be absorbed by editing the test |

## Iteration package

> Sibling paths under `{ITERATION_DIR}/<iteration-id>/` — not in `{SPECS_DIR}/` or `{KNOWLEDGE_DIR}/`. Promoted to knowledge at iteration-close via **`mstar-compound`**.

| Path | Purpose |
|------|---------|
| `guides/` | The 2026-09-12 audit evidence (defect list + measurements) that scopes this iteration; `scope-rationale.md` (spec-point traceability, dropped-detail note, corpus-scale source, acceptance-surface origins); `hygiene-report.md` (writing-specialist Phase 1 corpus-hygiene and naming-consistency findings) |
| `specs/` | Iteration-scoped spec drafts |
| `README.md` | Package document index |

## Quality Gate Summary

> Filled at iteration-close. Human summary only; per-plan gate details stay in each main plan, and open residual SSOT stays in `{PROJECT_DIR}/<id>/residuals.json`.

| plan_id | QC decision | QA gate | Residuals | Durable summary |
|---------|-------------|---------|-----------|-----------------|
| 20260912-gpu-enablement-truth | — | — | — | — |
| 20260912-batch-model-reuse | — | — | — | — |
| 20260912-quality-signal-merge | — | — | — | — |
| 20260912-asr-provenance-identity | — | — | — | — |

Notes:

- Raw review bundle: `{SDD_DIR}/review/` (ephemeral; do not rely on it after Done).
- Open residual SSOT: `{PROJECT_DIR}/<id>/residuals.json` `entries[<plan-id>]` (default `{HARNESS_DIR}/projects/<id>/`).

## Compound Round Summary

> Filled at iteration-close.

- 结晶文档数：<N>
- 新增 CONCEPTS.md 条目：<N>
- 触发 compound-refresh：<是/否>

## Iteration Retrospective (minimal)

> Filled at iteration-close.

- 做得好的：
- 可改进的：
- 下迭代建议：
