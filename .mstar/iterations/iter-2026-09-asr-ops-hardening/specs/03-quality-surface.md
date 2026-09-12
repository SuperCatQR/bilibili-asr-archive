---
spec: 03-quality-surface
iteration: iter-2026-09-asr-ops-hardening
owner_plan: 20260912-quality-signal-merge
spec_point: 3 — One quality surface | serves: A3 (guard: A6)
status: draft — iteration-scoped, promoted or dropped at iteration-close
---

# Contract 03 — One quality surface: content reasons in `coverage --quality`

## Contract

`bili-asr coverage --quality --archive-root <root>` answers the whole question. The seven structural codes keep their
spelling, order, `to_dict()` shape and exit semantics; seven content codes join the same vocabulary and are advisory
(they never change `valid_work_items` or the exit code). `scripts/asr_quality.py` and
`tests/test_asr_quality_script.py` are deleted, each output having a named replacement below.

## Decisions

- **D3.1 Seven codes appended to `REASON_CODES`** (quality.py L15–23), never reordering the existing seven (their
  index drives sorting, L97): `low_confidence`, `leading_mark`, `fragment_cue`, `overlong_cue`, `duplicate_cue`,
  `repeated_ngram`, `reference_disagreement`. *Rejected:* a per-row `signals` block — A3 says "as a reason in the
  existing vocabulary".
- **D3.2 Two classes, one rule.** `DEFECT_REASON_CODES` = today's seven; `CONTENT_REASON_CODES` = the new seven.
  `_cmd_coverage_quality` (cli.py L1289–1292, L1382) computes `has_defects` and `valid_work_items` from defect codes
  plus diagnostics only; content codes appear in `rows[].reasons` and `summary` counts and change nothing else.
  *Rejected:* uniform "any reason → exit 1" — measured on the recorded fixture (95 cues) the new vocabulary fires
  `low_confidence` (1 cue) and `overlong_cue` (2 cues, max 63 chars), so it would flip every real ASR archive from
  exit 0 to exit 1 and void the exit code's integrity meaning (compass risk row L204). *Rejected:* making
  `fragment_cue`/`leading_mark` defects because they are shaper invariants (guide L32–34) — they also fire on the
  upstream-caption path, where such cues are normal; A6 and `tests/test_asr_cues.py` enforce those invariants.
- **D3.3 One parser, richer cues.** `_read_cues` (quality.py L193–256) returns `(start, end, text, confidence)`
  records: structural checks read `start`/`end` as today, content checks read `text` (SRT cue line; JSON `text`,
  falling back to `content`) and `confidence` (JSON). Same single pass, same caps, no extra file opened. *Rejected:*
  a second content reader — two parsers drift.
- **D3.4 Thresholds.** `LOW_CONFIDENCE` is imported from `archive` (L278) so the reason and the archived count
  cannot disagree; `OVERLONG_CHARS = 60`, `FRAGMENT_MAX_CHARS = 6`, `FRAGMENT_MAX_SECONDS = 1.0`,
  `REFERENCE_AGREEMENT_FLOOR = 0.95` are declared in `quality.py`, ported **verbatim** from the retired script
  (L33–36, L121–122) including its strict comparisons, with a focused test asserting they equal `asr._CUE_MAX_CHARS`
  / `_CUE_MIN_CHARS` / `_CUE_MIN_SECONDS` (asr.py L129–135). *Load-bearing:* three existing assertions use exactly
  1.0 s cues (test_quality.py L267, L277; test_cli_help.py L315's exact list `["non_monotonic", "overlap"]`), so an
  inclusive `duration <= FRAGMENT_MAX_SECONDS` flips all three.
- **D3.5 Two recorded deviations.** `leading_mark` requires non-empty text (`text and text[:1] in LEADING`), because
  `text[:1] in LEADING` counts a text-less cue as a mark in Python, and quality.py parses caption JSON without
  `content` (test_quality.py L84–90). `repeated_ngram` keeps the script's **8**-gram ≥ 3× metric (L112–113), not the
  guide's 4-gram audit figure (guide L57): A3 pins the retired script's signal list.
- **D3.6 Confidence source.** Per-cue confidence comes from the raw sidecar `transcripts/raw/{stem}.json`
  `segments[].confidence`, already inside the read loop's inferred artifact list (quality.py L156) — no model
  invocation, no network, no re-run. Rows without scores (subtitle path, SRT-only fixtures) get no `low_confidence`
  reason — not computed rather than fabricated, with `source` already saying why, and no new diagnostic for that
  case.
- **D3.7 Reference agreement = `--reference <path>` on the same command,** accepted only with `--quality` and when
  the selection resolves to exactly one row (`--scope <work_id>`; `_select_scope`, coverage_report.py L397–421),
  else exit `1` and `coverage: --reference needs exactly one selected row (got N)`. Flattening + `SequenceMatcher`
  ported from the script (L39–40, L116–122), bounded by `_MAX_BYTES`; an unreadable or oversized reference is a
  usage error (exit 1, `coverage: reference unreadable`), never a traceback. Reported as reason
  `reference_disagreement` below the floor, plus a JSON top-level block `"reference": {"work_id", "reference",
  "agreement", "floor"}` with `reference` as the **basename only** (`[redacted]` if it trips the forbidden-marker
  scan); CSV keeps its frozen columns and puts the ratio on stderr. *Rejected:* `--reference <dir>` with stem
  matching — a naming convention for a signal that is inherently per-transcript.
- **D3.8 `--fail-under` is not ported.** The script's exit knob (L124–126) is superseded: the mean is already
  archived per row (`asr_mean_confidence`, archive.py L293) and the reason set drives the exit code. *Rejected:* a
  `--fail-under-mean` flag — a second verdict surface on a report that makes no semantic-correctness claim (README
  L345).

## Retirement map — every output of `scripts/asr_quality.py`

| Retired (script line) | Replacement |
|---|---|
| header `transcript`/`produced by`/`scale` (L78–85) | `coverage --quality` row (`work_id`, `source`, `language`, `status`, `cue_count`) + archived `asr_*` keys |
| confidence mean/p10/min + count (L87–98) | reason `low_confidence`; `asr_mean_confidence`, `asr_low_confidence_cues`, `asr_low_confidence_at` (contract 04) |
| top-3 unsure locations (L96–98) | `asr_low_confidence_at` — **all** locations, not the first three |
| mark / fragment / over-long / duplicate (L104–109) | reasons `leading_mark`, `fragment_cue`, `overlong_cue`, `duplicate_cue` |
| repeated 8-gram ≥ 3× (L112–113) | reason `repeated_ngram` |
| agreement (L116–122) | reason `reference_disagreement` + JSON `reference` block |
| "no cues found", exit 1 (L72–74) | existing reason `empty` (quality.py L87–88) |
| `--fail-under` (L124–126) | not ported (D3.8) |

## Boundaries — must not change

- `REASON_CODES[0:7]` spelling and order; `QualityResult.to_dict()` keys (quality.py L43–52); the CSV column tuple
  (cli.py L1327–1342); `schema_version: "coverage-quality-v1"`; the denominator block.
- Exit semantics for structural defects and diagnostics (cli.py L1382; README L342); read-only — nothing new opened,
  nothing written, no source sidecar mutated (README L310); `_MAX_BYTES`/`_MAX_CUES` and containment (quality.py
  L68–90, L185–190) unchanged.
- `tests/test_quality.py` and `tests/test_coverage_report.py` pass with their assertions unmodified (A3). The same
  immutability extends to the coverage-quality tests in `tests/test_cli_help.py` L249–348 — *not* the two files A3
  names, yet they hold the exact reason lists and exit codes.
- Cue shaping and transcript text: `asr.py` L125–135 / L447–546, `tests/test_asr_cues.py`,
  `tests/fixtures/asr-cues/` untouched (A6).
- Inherited non-goals: no accuracy re-tuning, model replacement, hotword/ITN change, gold standard, or manifest
  compaction (compass L130–160).

## Traceability

| Decision | Forced by |
|---|---|
| D3.1, D3.3, D3.6, D3.7 | guide §4.3 L103–109 (two entry points for one question); §3 L73–74 (per-cue confidence only in `raw.json`); A3 "reported when a second transcript is supplied"; scope-rationale L67–70 |
| D3.2 | compass risk row L204 (additive, existing command contract preserved); design choice for the defect/content split |
| D3.4, D3.5 | A3 "the seven existing codes and their tests held fixed" + `git show <iteration-base>:scripts/asr_quality.py` |
| D3.8 | design choice with rationale above; `--fail-under` is not in A3's signal list |

## Amendment request

`{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md` guidance 6 (L80–81) reads "Quality reason codes
describe structural artifacts only and never claim semantic correctness." The invariant preserved here is *no
semantic-correctness claim*; the structural-only clause needs "…describe structural artifacts and recorded content
measurements only; only the structural codes affect validity counts and exit status; none claims semantic
correctness." Requested at iteration-close via `mstar-compound` — not edited by this draft.

## Check the plan must run

On the 2026-09-12 output root (or a fresh single-item ASR run) record before/after `coverage --quality` output: same
seven codes with the same values, new codes present, `valid_work_items` and the exit code unchanged. If any named
exact-equality assertion moves, the ported threshold is wrong — fix the threshold, never the assertion.
