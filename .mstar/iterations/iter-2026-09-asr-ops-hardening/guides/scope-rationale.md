# Scope rationale — iter-2026-09-asr-ops-hardening

Companion to `delivery-compass.md`. The audit guide
(`2026-09-12-ten-video-audit.md`) is the *evidence*; this document is the *traceability*:
which measured line each spec point rests on, which claims were checked in the repository,
which accepted detail could not be sourced and was therefore dropped, and where the
acceptance-criteria surfaces come from. Written 2026-09-12 by `@product-manager` during the
Phase 1 direction-lock review; it is iteration-package evidence and is promoted (or dropped)
at iteration-close, not edited by implementers.

## 1. Spec-point traceability

"Evidence" = section and line range in `2026-09-12-ten-video-audit.md`. No point was killed
or merged: all five trace to a measurement. "Repo check" = what was inspected in the
checkout to confirm the surface the point describes still exists as described.

| # | Point | Evidence (audit guide) | Measurement it rests on | Repo check (2026-09-12) | Plan |
|---|-------|------------------------|-------------------------|-------------------------|------|
| 1 | Truthful GPU enablement | §4.1 L78–93 | ROCm 5.7 has no `gfx1101` (L84); PyTorch.org wheel imports with `torch.cuda.is_available()` `False` and aborts with `Found 0 rocprofiler agents and 2 HSA agents` under `HSA_ENABLE_DXG_DETECTION=1` (L85–87); verified device `gfx1101`, 15.8 GB, matmul on device via ROCm 7.2.1 + ROCDXG + repo.radeon.com wheel (L88–93) | `README.md` L20–24 (ROCm 5.7+ / `download.pytorch.org/whl/rocm6.0`); `src/bili_asr/asr.py` L320–322 (same URL in the runtime hint); `tests/test_asr_reproducibility.py` L330–351 (hint test asserting only `ROCm`/`7800XT` present) | P1 |
| 2 | Reachable, stated batch model reuse | §4.2 L95–101 | 21.8 min wall = ≈ 16.3 min decode + ≈ 5.6 min per-item overhead = 26 % (L101, L28–30) | `src/bili_asr/coordinator.py:494` (`if self.asr_runner is None:`); reuse oracle `tests/test_asr_reproducibility.py::test_target_runner_reuse_oracle_is_target_facing` (L186); construction counter in `::test_fixture_benchmark_reports_only_construction_and_shape` (L312) | P2 |
| 3 | One quality surface | §4.3 L103–109 | Shape layer owns seven reason codes; the content layer (confidence, fragments, over-long cues, repeated n-grams, cross-system agreement) lives in a parallel script the coverage surface does not know | `src/bili_asr/quality.py` L15–22 (`REASON_CODES`, exactly the seven named); `scripts/asr_quality.py` present as a second entry point; `tests/test_quality.py`, `tests/test_coverage_report.py`, `tests/test_asr_quality_script.py` present | P3 |
| 4 | Declared producer identity | §4.4 L111–115 | All ten archived files record `asr_model_name: "[redacted]"` | Redaction rule `src/bili_asr/asr.py` L396–413; frontmatter write `src/bili_asr/archive.py` L321 (`asr_` + provenance key); observed shape in an archived transcript (`.tmp/asr-e2e/transcript.md`: `asr_model_name: "[redacted]"`, `asr_model_revision: ""`) | P4 |
| 5 | VAD capture + low-confidence locations | §3 L68–74 (+ §2 L61–63, §1 table) | 1–15 gaps > 3 s per video (`BV1147c6sEKs` 15, `BV1eiPczHEqg` 15) with no recorded VAD capture; `asr_low_confidence_cues` is a count with no location; 11 cues ≤ 0.4 confidence, English/numbers carrying half | `src/bili_asr/archive.py` L275–295 (`LOW_CONFIDENCE = 0.4`, count written, no locations); no `asr_vad_*` capture keys in provenance (`ASRConfig` records only `vad_model` / `vad_max_segment_s`) | P4 |

Both halves of point 5 were kept in one point deliberately: they were measured in the same
run and the same record surface answers both (frontmatter + raw sidecar).

## 2. A detail that was dropped, not sourced

The pre-review compass asserted the target as "WSL2 + RX 7800 XT + Windows driver
32.0.31035.1003". The driver version appears in **no** evidence file in this repository, and
the target host is not reachable from this checkout (no `/opt/rocm*`, no ROCm tooling here),
so it could not be verified. Per the iteration's "everything here is measured" discipline
(audit guide L3–5) it was removed from the Scope point rather than carried as provenance-free
detail. The point itself is unaffected: the measured claims are about ROCm/driver versions
in the guide's §4.1.

## 3. Source for the Roadmap `Next` figures (63 parts, 449 s–9151 s)

The Roadmap Position's next-iteration figures are **not** in the audit guide (the guide
measures only the ten shortest parts, 449 s–1115 s). They were read from the live archive
database, read-only:

```
python3 -c "import sqlite3;c=sqlite3.connect('file:.tmp/e2e-23191782/archive/archive.db?mode=ro',uri=True);\
print(c.execute('select count(*), min(duration_ms), max(duration_ms) from video_parts').fetchone())"
→ (63, 449000, 9151000)
```

so: 63 visible parts, shortest 449 s, longest 9151 s, total ≈ 334 594 s ≈ 93 h of audio.
Recorded here so the compass's `Next` row is checkable without re-deriving it; if the corpus
grows, the figure moves with it and this note is the place to correct.

## 4. Where the acceptance surfaces come from (A1–A6)

Criteria were rewritten so each is falsifiable by a command, a test, or an archived field;
the check surfaces are:

- A1 — the self-check's exit code plus the three named invariants (device visible /
  `asr_device` recorded / exit code), and a grep-able negative (no
  `download.pytorch.org/whl/rocm` anywhere in docs or hints) instead of a transcript of a
  good run. The `asr_device` field already exists (`archive.py` L321 + `ASRConfig.device`),
  so the criterion checks a real archived field, not a new one.
- A2 — the construction counter that already exists in the reproducibility suite, applied to
  a multi-item batch, plus one printed count. It deliberately does **not** claim a wall-clock
  speed-up.
- A3 — the retired script's own signal list (`git show <base>:scripts/asr_quality.py`) versus
  the coverage surface's reasons, with the seven existing codes and their tests held fixed.
  The reference-agreement signal is included because "the parallel script retires" would
  otherwise silently drop a capability the operator has today.
- A4 — archived frontmatter fields plus the two existing redaction tests, reproduced from
  `README.md` alone.
- A5 — the archived frontmatter keys `asr_vad_segments`, `asr_vad_captured_s`,
  `asr_vad_captured_ratio`, `asr_low_confidence_at`. These spellings are the acceptance
  surface chosen here (the `asr_vad_*` family already exists through `ASRConfig.vad_model` /
  `vad_max_segment_s`); a plan may rename them only by amending the compass, so the criterion
  and the shipped field cannot drift apart.
- A6 — fixture + assertion immutability across the iteration diff, so a text regression
  cannot be absorbed by loosening a test.

## 5. Evidence deliberately not leaned on

- The audit's earlier ad-hoc "rare character" count was wrong (guide §2 L65–66) and is not
  used by any criterion or spec point.
- Per-cue confidence decomposition in §2 L61–63 is used only to justify *recording*
  low-confidence locations (point 5), not to claim an accuracy defect to fix.
- §5 of the guide ("checked and *not* defects") is used only as non-goal evidence — audio
  reclaim, manifest append revisions, `verify`/integrity expectations.
