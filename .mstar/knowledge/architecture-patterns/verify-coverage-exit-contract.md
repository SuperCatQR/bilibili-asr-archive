---
module: bili-asr verify / coverage readers
date: "2026-09-27"
problem_type: architecture_pattern
category: architecture-patterns
severity: high
plan_id: 20260927-evidence-dashboard
applies_when:
  - changing verify, coverage or any reader that emits an exit code
  - classifying findings into defect vs backlog classes
  - widening or narrowing a reader's probe set
  - reviewing a fix whose stated goal is reader agreement
  - claiming two readers agree on a set of input shapes
tags:
  - exit-codes
  - two-class-findings
  - reader-agreement
  - strict-mode
  - backlog-vs-defect
  - containment-probes
---

# verify / coverage exit contract: two finding classes, and reader agreement as a pair property

## Context

`bili-asr verify` and `bili-asr coverage` are the two public readers of one archive, and
for most of the product's life they treated "work not yet done" as an error: a healthy
archive holding 84 unprocessed rows exited `1` with 84 `retryable_incomplete` findings,
which made cron unusable — the exit code answered "is there anything left to do?", not
"is the archive broken?". The fix is a re-classification at the CLI boundary, not a new
findings taxonomy, and the harder half of the work turned out to be keeping the two
readers in agreement while their probe sets were widened one candidate at a time.

## Guidance

### The two-class contract

`verify` and `coverage` partition findings into exactly two classes:

| Class | Meaning | Exit contribution (default) |
|-------|---------|------------------------------|
| `defect` | archive corruption / format violation — malformed manifest JSONL, schema-violating rows, store inconsistency, an artifact path that escapes every read base | non-empty → exit `1` |
| `backlog` | work not yet done — `retryable_incomplete`, `needs_audio` / `pending` rows, `retryable_attempt`-shaped row diagnostics | reported in a separate `backlog:` section; **zero effect on exit code** |

- Default invocation: exit `0` when the archive is well-formed, **regardless of backlog
  size**. Malformed ≠ backlog, as code-able assertions: a manifest that parses and whose
  rows satisfy the manifest schema is **well-formed** and must not surface as `defect`;
  append-only history (multiple rows sharing one `work_id`) is not itself a defect;
  a coverage denominator is "unavailable" only on a genuine read/parse failure, never as
  a forced override.
- `--strict` restores pre-cutover behaviour: any finding of either class → exit `1`.
  Documented as the CI/compatibility mode.
- **Well-formedness of the manifest format is necessary but not sufficient.** A
  schema-valid row whose declared artifact path escapes the archive root is an
  artifact-identity defect, not a manifest-format problem; it stays defect-class. A
  sentence that conflates the two ("a well-formed manifest can never surface as defect")
  is narrowed, not obeyed.
- **A terminal-complete row (`gone`) is in neither class** and never moves an exit code,
  in any mode, on any command. §2's `--strict` restores pre-cutover behaviour "for
  findings of either class"; a terminal-complete row is not a finding, so `--strict` has
  nothing to see. Recorded so no later reader re-opens it.

### Reader agreement is a property of the reader PAIR

The stated goal is *one archive, one verdict*. That is a property of the pair of readers,
and it has three consequences that each cost a fix round to learn:

1. **Neither reader is "the reference".** A fix that widens one reader's probes to match
   the other must then re-check the pair, because the widening can *create* a new
   disagreement in the other direction. The measured case: widening `verify`'s
   inferred-raw containment probe (to close a verify-0 / coverage-1 disagreement) made
   `verify` ask the containment question unconditionally, while `coverage` still gated its
   inferred candidates on `exists()` — turning an escaping-but-absent path (a dangling
   escaping symlink) into a verify-1 / coverage-0 disagreement that did not exist before
   the fix. **The "verbatim patch" provenance of a change is not a defence, and neither
   is fail-closed direction: a pair that disagrees in either direction fails the plan's
   own statement.**
2. **Candidate sets must be enumerated from the readers' own tables, not from the shapes
   already known.** The agreement sweep that passed 15/15 was true for the shapes it
   listed while excluding both `transcripts/raw/` and escaping-but-absent candidates —
   which is how the two surviving disagreements survived it. Both raw locations are
   writer-real (`archive.py` declares `raw_path` under `transcripts/raw/`, `subtitles.py`
   writes `subtitles/raw/`), so inferring only one was an incomplete candidate set, not a
   deliberate boundary. Existence is the wrong gate for a question about *where a path
   points*: an escaping relative path can be absent and still resolve outside every
   base, and a directory component that is itself an escaping symlink is invisible to a
   leaf-level `is_symlink()` test.
3. **A test that pins a disagreement the plan exists to remove is not a valid regression
   guard.** The shipped suite contained a test pinning verify-exit-0 for exactly the
   shape under repair; the fix flipped it to pin agreement (both readers exit 1 on the
   same fixture), with a no-op control for the absent-but-confined case.

### Containment probes: flag where the path points, never its absence

The defect class for escaping paths is `IDENTITY_PATH_MISMATCH` (already the owner of
"declared path is unsafe or not canonical"); do not invent a second verify-side code for
the same condition. The probe rules:

- Apply containment probes to the same candidate set both readers use: declared
  `raw_path`, declared `artifact_path` / `artifact_paths`, and the inferred raw paths —
  for **every status**, not just terminal ones. A manifest row whose declared or inferred
  path escapes the archive root is corruption regardless of the row's status; a reader's
  silence on in-flight rows is a gap in its probes, not a class boundary.
- Flag a path **only when it escapes every base** — never for mere absence. "The artifact
  is not created yet" stays backlog. The widened probe is a no-op on well-formed archives
  because shipped writers emit canonical relative paths; it fires only on hand-edited or
  legacy rows.
- The inferred families are **alternatives, not conjuncts** (srt / txt / raw@transcripts /
  raw@subtitles / md globs): offering every absent inferred candidate as its own
  `artifact_missing` regressed six existing tests and flipped a healthy archive to exit 1.
  An absent inferred candidate is offered only when it escapes every read base.
- Suppress the secondary signal: `MISSING_RAW_SUBTITLE` is asked **only for a confined
  path**. When the inferred raw resolves outside the base, the document is not "missing"
  — naming the same containment failure twice with the less accurate name measurably
  widens the recovery surface (`recover --defect-code missing_raw_subtitle` changed its
  exit and its selected set). A row-level flag ("anything in this row's inferred set
  escapes") is the form that actually suppresses the ask; a per-candidate skip does not,
  because the confined sibling is absent and the ask fires anyway.

### CLI-side reader defects the exit rule cannot fix

Two reader-layer gaps were found while wiring the exit contract, both outside what an
exit-rule change can reach: a malformed manifest line that the reader `continue`s past
(silently dropping both the defect and the backlog for that line), and a `verify` that
silently dropped `manifest_malformed` into an empty defects list. The fix appends the
existing defect-class constant instead of continuing. The durable rule: **the exit layer
can only classify the findings a reader surfaces; a reader that swallows an input shape
makes the whole contract unverifiable for that shape** — catch it with a fixture whose
single malformed line must produce a named defect, never an empty report.

## Why This Matters

The operator-facing win is that cron and scheduled checks become usable: exit 0 means
"the archive is intact", exit 1 means "something is broken", and the backlog section
reports work remaining without failing the check. The engineering win is sharper: each
round of "widen one reader to match the other" produced a new disagreement in the
surviving direction, and only treating agreement as a pair property — with the candidate
set enumerated from the readers' own tables and a flipped test as the regression guard —
closed the loop. A stricter reader that the other cannot match satisfies fail-closed
while failing the actual requirement.

## When to Apply

- Changing `verify`, `coverage`, or any future reader that emits an exit code over shared
  findings: classify at the CLI boundary into the two classes; keep `gone` in neither.
- Widening or narrowing any reader's probe set: re-run the pair agreement check over the
  full candidate enumeration, not the shapes the fix was written for.
- Reviewing a fix whose stated goal is reader agreement: ask which disagreement the fix
  *creates*, enumerate candidates from the readers' own tables, and flip any test that
  pins the old disagreement.
- Adding a new finding code: decide its class explicitly, reuse `IDENTITY_PATH_MISMATCH`
  for identity/containment rather than inventing a parallel code, and state the choice in
  the report.

## Examples

- `bilibili-asr-archive/src/bili_asr/integrity.py` — the `verify` reader: containment
  probes over the full candidate set for every status, `IDENTITY_PATH_MISMATCH` as the
  single identity code, `MALFORMED_ARTIFACT` appended (not `continue`d) for a malformed
  line.
- `bilibili-asr-archive/src/bili_asr/quality.py` — the `coverage` reader: `_artifact_paths`
  offers an absent inferred candidate only when it escapes every read base, and asks the
  containment question regardless of existence.
- `bilibili-asr-archive/tests/test_integrity.py` — the flipped test that pins the pair's
  agreement (verify exits 1 with `identity_path_mismatch`, matching `coverage --quality`)
  plus the no-op control for the absent-and-confined case.

## Evidence

- Iteration `iter-2026-09-coverage-truth`; plan `20260927-evidence-dashboard`.
- Contract and rulings: `{ITERATION_DIR}/iter-2026-09-coverage-truth/specs/exit-code-contract.md`
  §2 (two classes), §2b (retryable_attempt = backlog; `gone` = neither), §2c (`gone`
  non-exit-bearing in both modes), §2d (widen verify, not narrow coverage), §2e (widen
  the inferred-raw candidate too; flip the test), §2f (agreement is a pair property;
  both readers move; suppress the side effect), §2g (two measured deviations from the
  briefed patches accepted as corrections of PM patch bugs), §3 (caller impact: zero
  migration).
- Plan-QC record (three seats, basis-drift disclosed):
  `{SDD_DIR}/20260927-evidence-dashboard/review/qc-consolidated.md`; fix rounds
  `4cf4fea` (§2e) and `cafb0ca` (§2f, with §2g's accepted deviations).
- Measured headline case: `e2e-23191782-subtitle-publish-webdav` (84 `needs_audio` rows /
  84 `retryable_incomplete` / 6 published rows clean) exits `0` and prints the backlog
  section.

## See also

- [operational-sidecars.md](operational-sidecars.md) — the quality reason-class split
  (defect codes decide validity, content codes are advisory) this exit contract extends;
  the manifest well-formedness rule (append-only history is well-formed) it pins at the
  CLI layer.
- [pairing-rule-travels-with-behaviour.md](../best-practices/pairing-rule-travels-with-behaviour.md)
  — the same reader-agreement family measured on a different value (which base holds a
  recorded path): enumerate every pairing site, and make agreement the acceptance
  criterion.
- [absence-assertion-negative-control.md](../testing-patterns/absence-assertion-negative-control.md)
  — the flipped-test rule (a test that pins the disagreement the plan exists to remove is
  not a regression guard) is one instance of the reachable-falsifier rule.
