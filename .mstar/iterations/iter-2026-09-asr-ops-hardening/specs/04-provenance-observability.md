---
spec: 04-provenance-observability
iteration: iter-2026-09-asr-ops-hardening
owner_plan: 20260912-asr-provenance-identity
spec_points: 4 — Declared producer identity; 5 — ASR observability | serves: A4, A5 (guard: A6)
status: draft — iteration-scoped, promoted or dropped at iteration-close
---

# Contract 04 — Declared identity + captured-audio facts in provenance

## Contract

An archive can say *which* model produced a transcript without serializing a path, and *how much* audio the capture covered
and *where* the doubt is. The operator declares the hub-level identity through `BILI_ASR_MODEL_ID`; it lands in the slot
`asr_model_name` already occupies, never as a second key. Four new frontmatter keys carry the capture facts, computed in
`archive.py` from the segments it already publishes.

## Decisions

- **D4.1 New env var `BILI_ASR_MODEL_ID`** (constant `ASR_MODEL_ID_ENV_VAR` beside the others, asr.py L56–61), read by
  `default_config()` (L229–239) into a new `ASRConfig.model_id: str | None = None` field appended **last** in the dataclass,
  so existing positional construction (`ASRConfig("model", model_revision="rev")`, test_asr_reproducibility.py L169/L242)
  does not shift. It never changes the load: `BILI_ASR_MODEL` stays the value the loader receives (asr.py L221–227).
  *Rejected:* pointing `BILI_ASR_MODEL` at the hub id — the pinned checkpoint is a remote-code model with no FunASR alias.
  *Rejected:* a `--model-id` CLI flag — unattended runs have no per-row flag surface.
- **D4.2 Validation is loud, not silent** (`__post_init__`, asr.py L160–190, following the `local_source` precedent
  L189–190): a declared id must satisfy `_MODEL_IDENTIFIER.fullmatch(value)` (L43) **and** contain `"/"` **and** not match
  `_FORBIDDEN_PROVENANCE` (L39–42), else `ValueError("BILI_ASR_MODEL_ID must be a hub-level model identifier")`, which
  surfaces through the existing per-item failure path and exit `1`. *Rejected:* silently falling back to `[redacted]` — the
  operator would believe the archive names its producer.
- **D4.3 Precedence in `provenance()`** (asr.py L396–413): (1) declared `model_id`; (2) else the configured `model_name`
  when it is itself redaction-safe (`_MODEL_IDENTIFIER.fullmatch`, the existing rule L405–407); (3) else `[redacted]`. If
  `model_name` is *itself* a **hub-level** safe identifier (`hub_level=True`) and differs from a declared `model_id`,
  construction raises `ValueError` — a declaration contradicting the load value would make the archive lie.
  **Amended twice at plan QC (seat 2, F-002, 2026-09-13).** First attempt said "hub-level only
  (`hub_level=True`)" — that does **not** fix the defect, because `hub_level` is satisfied by any slash-qualified
  string: `models/Fun-ASR-Nano-2512` and `Qwen/Qwen2.5-7B` both pass it (measured). The predicate is therefore
  **hub-level AND the value must not resolve to a directory on this machine**: a configured `model_name` that names
  an existing local directory is a load *location*, not a competing identity, so it cannot contradict a declaration.
  That keeps exactly the case this route exists for (two different hub ids) and stops punishing the documented
  relative-path form. Both directions are pinned by test. *Rejected:* emitting a separate `asr_model_id` key —
  two keys for one identity drift, and A4 names `asr_model_name` as the carrier.
- **D4.4 `model_id` is a slot replacement, never a key.** `provenance()` keeps exactly the nine keys
  `::test_provenance_has_stable_redacted_configuration_keys` (L221–224) pins, in the same order: `model_id` is skipped while
  rendering and only substitutes into the `model_name` slot, which still passes the existing scan.
- **D4.5 Revision companion = the existing `BILI_ASR_MODEL_REVISION`** → `asr_model_revision`, keeping its dual role (loader
  kwarg when set, asr.py L346–347; recorded value) — no new variable, no loader change;
  `::test_factory_gets_exact_kwargs_and_typeerror_is_not_retried` (L158–177) pins the kwarg set and stays green.
  *Assumption, stated not deferred:* passing `model_revision` with a local checkpoint directory is accepted by the pinned
  loader — today's behaviour, unverifiable here (no target host, no FunASR). *Check P4 must run:* one load on the host with
  the revision declared, one without; if it breaks the local-dir load, record an amendment request to split the variable
  instead of shipping a broken kwarg.
- **D4.6 A5's spellings are adopted as written** (`asr_vad_segments`, `asr_vad_captured_s`, `asr_vad_captured_ratio`): no
  compass amendment, since they extend the existing family (`asr_vad_model`, `asr_vad_max_segment_s`; scope-rationale
  L73–77). **"Captured" is defined**, because the model's result carries no VAD boundary list: captured spans are the
  transcript's cue intervals with touching, overlapping and sub-threshold-adjacent intervals merged, adjacency threshold
  `CAPTURE_GAP_SECONDS = 1.0` — the shaper's own pause threshold (asr.py L130). `asr_vad_segments` = number of merged spans;
  `asr_vad_captured_s` = their summed duration (never more than wall-clock); `asr_vad_captured_ratio` = `min(1.0, captured /
  duration_s)`, `duration_s` from the same frontmatter (archive.py L318); all rounded to 3 decimals like
  `asr_mean_confidence` (L293). The ratio key is omitted when `duration_s` is not positive and finite; `asr_vad_captured_s`
  stays unclamped so a duration/cue contradiction stays visible (`out_of_range` is its detector). *Rejected:* counting cues
  directly — a cue boundary is a punctuation or 60-char decision, not a capture boundary. *Rejected:* 1-decimal rounding —
  it would make A5's recompute inexact.
- **D4.7 Gating and site.** The three capture keys are written iff `source == "asr"` — only the ASR path has a VAD, and the
  subtitle path is pinned by `::test_write_archive_without_provenance_adds_no_asr_keys` (L244–249, asserts `"asr_" not in
  md`). They are computed in `archive.py` as a sibling of `_confidence_summary` (L281–295) and applied inside
  `write_archive` beside the existing `asr_*` update (L318–321), because publication is where every frontmatter key is
  assembled. `archive.py` may not import `asr.py` (asr-archive-cli.md L58, L61), so `CAPTURE_GAP_SECONDS` is declared
  locally with a focused test asserting it equals `asr._CUE_MAX_GAP_SECONDS`. *Rejected:* computing in `asr.py` and
  threading it through provenance — provenance is `asdict(ASRConfig)`, configuration, not measurement. *Rejected:* computing
  in the analyzer — A5 needs the fact **recorded**, and the analyzer is a reader.
- **D4.8 `asr_low_confidence_at`, format = JSON list of start seconds** (`[580.643, 812.4]`, ascending, 3 decimals, rendered
  by archive.py L324), same threshold `LOW_CONFIDENCE` (L278) and the **same computation** as the existing count:
  `_confidence_summary` (L281–295) emits `asr_low_confidence_cues` and `asr_low_confidence_at` together, so `len(list) ==
  count` by construction rather than by test. Emitted whenever scores exist — including an empty list when no cue is at or
  below the threshold — and absent when the transcript carries no scores, matching the count's existing rule (L319).
- **D4.9 The raw sidecar is unchanged** (`segments`, `source`, `provenance`; archive.py L325–328): it already carries the
  segments every new fact derives from, so A5's "recompute from `raw.json` segments" needs no new field, and
  `test_archive_md.py` L233 (`raw["provenance"] == provenance`) stays green.

## Exact names and shapes

| Surface | Name / value |
|---|---|
| env / config | new `BILI_ASR_MODEL_ID`, existing `BILI_ASR_MODEL`, `BILI_ASR_MODEL_REVISION`; field `ASRConfig.model_id: str \| None = None` (appended last, never emitted) |
| frontmatter (A4) | `asr_model_name` = declared hub id, else the safe configured id, else `"[redacted]"`; `asr_model_revision` = declared revision or `""` |
| frontmatter (A5) | `asr_vad_segments: <int>`, `asr_vad_captured_s: <float>`, `asr_vad_captured_ratio: <float in [0,1]>`, `asr_low_confidence_at: [<float>, …]`; computed in `archive.py::write_archive` with constants `CAPTURE_GAP_SECONDS` (new) and `LOW_CONFIDENCE` (existing) |
| README | declaration block (`BILI_ASR_MODEL` vs `BILI_ASR_MODEL_ID` vs `BILI_ASR_MODEL_REVISION`), the greps `^asr_model_name:`, `^asr_model_revision:`, `^asr_vad_`, `^asr_low_confidence_at:`, and "no declaration → `[redacted]`" |
| new tests | declared-identity case (hub id recorded; the path absent from frontmatter, `raw.json` and CLI output; loader input unchanged); no-declaration case keeps `[redacted]`; key presence, ratio bound and count-vs-list consistency recomputed from `raw.json`; forbidden-token scan; `CAPTURE_GAP_SECONDS` coupling |
| kept tests | L250, L265, L272–297, L210–236 of `tests/test_asr_reproducibility.py` (safe slash-qualified id, redaction of path/URL/credential, runtime-only env path, the nine stable provenance keys) |

## Boundaries — must not change

- The redaction rule itself (asr.py L405–412): paths, URLs and credential-like values are still never serialized — the
  declared id adds an *identity*, not an exemption; no frontmatter value, raw sidecar or CLI output gains a filesystem path
  (A4).
- `provenance()`'s nine keys and order (test L221–224); the `asr_` prefix and frontmatter key order (archive.py L318–324;
  `test_write_archive_layout_and_frontmatter` L21 asserts the opening lines); the subtitle path writes no `asr_*` key at all
  (test L244–249).
- Existing archives are never rewritten: the ten already-archived rows keep `asr_model_name: "[redacted]"`; this contract
  governs future writes only. Publication semantics (staged bundle, marker last, operational-sidecars guidance 11/L107) and
  the confined-path policy are untouched; contract 03 D3.7's basename-only rule keeps operator paths out of reports.
- Cue shaping and transcript text: `asr.py` L125–135 / L447–546, `tests/test_asr_cues.py`, `tests/fixtures/asr-cues/`
  untouched. The `md` frontmatter block gains keys; the `md` body, `srt` and `txt` bytes are unchanged
  (`segments_to_txt`/`segments_to_srt`, asr.py L584–592) — A6.
- Inherited non-goals: no accuracy/model/hotword/ITN change, no manifest compaction or JSONL schema change (compass
  L130–160; operational-sidecars L39–41), no new diagnostic for transcripts without confidence scores.

## Traceability

| Decision | Forced by |
|---|---|
| D4.1–D4.4 | guide §4.4 L111–115: all ten rows record `[redacted]` because a local path cannot be a redaction-safe identifier; run-scoped-asr-provenance L32 ("only redaction-safe opaque identifiers … and declared configuration intent"); A4's named carriers; boundary test L221–224 |
| D4.5 | A4 "the declared revision"; design choice — reuse the existing variable instead of adding a second one |
| D4.6, D4.7 | guide §3 L68–74 (1–15 gaps > 3 s per video, nothing records VAD capture) + A5's named keys |
| D4.8 | guide §3 L73–74 (`asr_low_confidence_cues` names a count, not a location); §2 L61–63 (11 cues ≤ 0.4) |
| D4.9 | A5 "recompute both from `raw.json` segments" — no new sidecar field needed |

## Amendment request

`{SPECS_DIR}/asr-archive-cli.md` L23 and L69 still name SenseVoice-Small / `iic/SenseVoiceSmall`, while the shipped default
is `FunAudioLLM/Fun-ASR-Nano-2512` (asr.py L22) and `BILI_ASR_MODEL` is documented as a local checkpoint directory (asr.py
L221–227). The drift predates this iteration and D4.1–D4.5 do not touch it; it is recorded here because A4's declared
identity names the current checkpoint. Requested when `{SPECS_DIR}` is next revised at iteration-close — not edited by this
draft.

## Checks the plan must run

1. Reproduce A4 from `README.md` alone on the host: declare the id, archive one item, read
   `asr_model_name`/`asr_model_revision`, and confirm the materialized path appears nowhere in frontmatter, `raw.json` or
   stdout.
2. Recompute `asr_vad_segments`, `asr_vad_captured_s`, `asr_vad_captured_ratio` and `len(asr_low_confidence_at) ==
   asr_low_confidence_cues` from `raw.json` plus `duration_s`, on the 2026-09-12 output root.
3. Confirm D4.5's assumption on the host (one load with the revision declared, one without) and record the outcome; if it
   fails, record the amendment request first.

## Plan-QC amendments (2026-09-13)

**D4.10 — zero-length cues are skipped when computing the capture facts** (plan QC seat 1 S-5, seat 2's
non-scored totality note). `normalize_result` can emit a text-only cue with `start == end == 0.0`
(`asr.py`) — a `zero-length` cue, `start == end == 0.0` — and the merger drops it so the published `asr_vad_segments` / `captured_s` count only real
spans; without the skip a naive recompute from `raw.json` would read one more segment than the archive
publishes. The shipped `<=` fusion boundary (a gap of exactly `CAPTURE_GAP_SECONDS` fuses) is the correct
capture reading and is pinned by test; the docstring's original "sub-second-adjacent" phrasing was wrong
(seat 2 F-004) and has been corrected in code.

**The capture keys answer "how much", not "where"** (seat 3 F-2): they discriminate a speaker pause from a
VAD miss on real material (24 spans / 413.63 s / 0.921 straight-through; 25 / 413.63 / 0.767 with a 90 s
pause injected; 19 / 334.76 / 0.621 with 90 s of cues deleted), but localising a doubtful stretch still
requires `raw.json`. `asr_low_confidence_at` is O(cues) in one YAML line (20 000 all-low cues ≈ 169 KiB) —
linear, bounded, and no reader breaks.
