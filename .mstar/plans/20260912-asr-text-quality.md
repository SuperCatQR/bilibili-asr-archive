# ASR text quality: corpus hotwords, cue sizing, and persisted provenance

> Standalone follow-up to `20260911-asr-nano-native-punctuation`. Compressed path
> (`specify(min) -> plan(min) -> implement`) per `mstar-phase-gates` § Hotfix 例外.
> Execution mode: `inline`.
> Trigger: operator request 2026-09-12 — "加一些热词表。cue 也优化一下。落盘 provenance。"

## Status

- Priority: P1
- Task category: backend / quality + traceability
- Status: Done (inline; branch `fix/20260912-asr-text-quality`)
- Depends on: `20260911-asr-nano-native-punctuation` (merged as `4645789`)
- Primary spec: `.mstar/specs/asr-archive-cli.md` + `{KNOWLEDGE_DIR}/architecture-patterns/run-scoped-asr-provenance.md`
- Owner: fullstack-dev (PM inline) · QA gate: pm-acceptance (hotfix path)
- Findings cleanup: zero-residual

## Goal

The archived transcript carries a corpus vocabulary bias, reads as well-formed cues in SRT, and
records which model, revision, device, VAD and hotwords produced it.

## Specify (measured defects from the 2026-09-12 review of `BV1wLTP6NE9h:p0`)

- **Q1 — no vocabulary bias.** Five homophone errors in 7.5 minutes on terms the corpus uses
  constantly: `公式` ← 攻势 (×2), `马鞍牌` ← **马恩牌** (×2, operator-confirmed), `智力豆包` ←
  智利豆包, `跟着苗红` ← 根正苗红, `转会差` ← 赚汇差. Nano supports `hotwords`, unused today.
- **Q2 — cues too fragmented.** 24/124 cues shorter than 1.0 s (shortest 0.06 s), 11 cues of
  ≤4 characters (`不。`, `的这个`, `。`), 3 cues opening with `，` because a pause split landed
  after the preceding mark. The SRT is choppy where the speaker pauses.
- **Q3 — provenance not persisted.** `raw.json` is `{"segments", "source"}` and the MD
  frontmatter carries `source: asr` only, so nothing in the archive says which model,
  revision, device, VAD or hotwords produced the text. `ASRRunner.provenance()` already
  returns that mapping and it is dropped on the floor.

## Clarify (decisions)

1. **Hotwords are configuration, not a hidden default.** `ASRConfig.hotwords` is a tuple
   (empty = none); `BILI_ASR_HOTWORDS` appends operator terms to a shipped corpus list
   (`DEFAULT_HOTWORDS`). They travel to the model as the model documents (`hotwords=[...]`)
   and are recorded in provenance. Bounded list: a long prompt dilutes the bias.
2. **Cue post-processing, not new split rules.** Splitting stays punctuation / ≥1 s pause /
   60-character ceiling; a second pass then (a) moves a leading mark onto the previous cue,
   (b) merges a cue that is punctuation-only or undersized (`<6` chars or `<1.0` s) into its
   neighbour while the 60-character ceiling holds. No text is dropped and no timing is
   invented: a merge keeps the earlier start and the later end.
3. **Provenance is written by the archive writer.** `write_archive` gains an optional
   `asr_provenance` mapping: it lands in `raw.json` under `provenance` and in the MD
   frontmatter as flat `asr_*` keys (greppable, JSON-encoded like the rest of the frontmatter).
   The subtitle path passes nothing and is unchanged.
4. **The CLI builds one runner per batch.** It currently calls the module wrapper per item,
   which reloads a 2 GB checkpoint for every video; provenance per item needs the runner
   anyway, so the batch now owns one runner and releases it at the end — the documented
   run-scoped reuse the coordinator already follows.

## Non-goals

- No `punc_model`, no VAD changes, no post-hoc editing of recognised text (the corpus list
  biases decoding, it does not rewrite output), no changes to the subtitle path, no SQLite
  audio stage.

## Architecture

- `src/bili_asr/asr.py`: `ASRConfig.hotwords`, `DEFAULT_HOTWORDS`, `BILI_ASR_HOTWORDS`
  parsing in `default_config()`, `hotwords` in the `generate` request, `hotwords` in
  provenance, and the cue post-processing pass.
- `src/bili_asr/archive.py`: `write_archive(..., asr_provenance=None)` → `raw.json` +
  `asr_*` frontmatter keys.
- `src/bili_asr/cli.py`: one runner per `asr` batch, provenance handed to the writer, runner
  released in a `finally`.
- `src/bili_asr/coordinator.py`: provenance handed to the writer from its existing runner.

## Verification

- `pytest -q`: **1335 passed, 4 skipped** at the final HEAD; new unit tests for hotword config, request shape, cue merging rules, and
  both provenance sinks.
- Live E2E on the same recording, comparing against the 2026-09-12 baseline (124 cues, 24
  under 1 s, 3 leading-mark cues): expect fewer/short cues merged, and check whether the five
  Q1 terms changed.

## Evidence log

Same recording (`BV1wLTP6NE9h:p0`, 448 s), same checkpoint, same box, shipped CLI:

| measure | baseline | after |
|---|---|---|
| cues | 124 | **94** |
| cues <1 s | 24 | **0** |
| cues ≤4 chars | 11 | **0** |
| cues opening with a mark | 3 | **0** |
| 马鞍牌 → 马恩牌 | 马鞍牌 ×2 | **马恩牌 ×2** |
| 公式 → 攻势 | 公式 ×2 | 攻势 ×1, 公式 ×1 |
| 智力豆包 → 智利豆包 | 智力豆包 ×1 | **智利 ×1** |
| 跟着苗红 → 根正苗红 | 跟着苗红 ×1 | 跟着苗红 ×1 (unchanged) |
| Latin words | `laborlaborgang` (merge glued tokens) | **`labor labor gang labor gang`** |
| provenance | none | `raw.json.provenance` + 8 `asr_*` frontmatter keys |

Runtime 4m29s (rtf 0.55, CPU); TXT 2193 chars with `。`×70 `，`×111 `？`×17.  Nineteen of the twenty-three shipped terms are unchanged
vocabulary that the model already handled; the four above are the measured error classes.

Open observation: with `BILI_ASR_MODEL` pointing at a local snapshot, provenance redacts
`model_name` (by design), so the archive records `[redacted]` — materializing the hub id at the
composition root (roadmap item 1 of the previous plan) is what closes that loop.

## Review Gate Summary

- PM self-review (compressed path): all three requests are implemented inside existing seams
  (ASR boundary, archive writer), every claim is reproduced by the live run above, and the one
  term the hotwords did not fix is reported rather than hidden.
- Residuals: none registered. Roadmap carried forward: hub-id materialization (closes the
  `[redacted]` model name), CLI batch model reuse (the boundary reloads a 2 GB checkpoint per
  `asr` row because the CLI keeps its module-level seam), and the SQLite audio stage.
