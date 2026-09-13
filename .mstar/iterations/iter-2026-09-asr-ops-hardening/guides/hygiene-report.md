# Phase 1 hygiene report — iter-2026-09-asr-ops-hardening

Writing-specialist report for the Phase 1 review chain (`mstar-iteration` §1.6). Swept: this
iteration package, `{SPECS_DIR}`, `{KNOWLEDGE_DIR}`, `{ITERATION_DIR}/README.md`, and every
sibling iteration package. Every fix below is anchored to the architect's spec as the decision
record; **no decision was changed, no requirement added, and no knowledge document was added
or edited.**

Fixed line numbers are post-edit anchors in this package.

## 1. Naming fixes applied (compass → spec)

| # | File:line | Before | After | Decided by |
|---|-----------|--------|-------|------------|
| F1 | `delivery-compass.md` L112 | A1 named the check only as "the environment self-check named in `README.md`"; the check column said "Run the self-check on the target" | A1 names it `scripts/check_asr_env.py`; the check column runs `python3.12 scripts/check_asr_env.py` | `specs/01-gpu-enablement.md` L25 (D1.2: the check is `bilibili-asr-archive/scripts/check_asr_env.py`, run as `python3.12 scripts/check_asr_env.py` from the repository root) |
| F2 | `delivery-compass.md` L112 | A1 negative grep: `grep -rn 'download.pytorch.org/whl/rocm' README.md src/` | `grep -rn 'download.pytorch.org/whl/rocm' README.md src/ docs/` | `specs/01-gpu-enablement.md` L52–56 (D1.7 states the contract extends the compass grep to `docs/`); corroborated by A1's own criterion sentence ("no document or error string still recommends…") and by `guides/scope-rationale.md` L61 ("anywhere in docs or hints") |
| F3 | `delivery-compass.md` L113 | A2 loop form written `bili-asr asr --bvid …` | `bili-asr asr --bvid <bvid>` | `specs/02-batch-reuse.md` L49–52 (D2.7 fixes the greppable literal as `bili-asr asr --bvid <bvid>`). Without this, A2's own "README statement greppable" check greps a string the README must not contain |
| F4 | `delivery-compass.md` L115 | "with no declaration `asr_model_name` stays `[redacted]`" | "with no declaration `asr_model_name` keeps the configured id only when that id is itself redaction-safe, and is `[redacted]` otherwise" | `specs/04-provenance-observability.md` L31–35 (D4.3 precedence: declared id → safe configured `model_name` → `[redacted]`) and L79 (frontmatter row). The old clause also contradicted A4's own named regression test `::test_provenance_preserves_safe_slash_qualified_model_identifier` (compass L115; test at `tests/test_asr_reproducibility.py` L250), which pins the safe-configured-id case |
| F5 | `delivery-compass.md` L214 | `guides/` row listed the audit guide + `scope-rationale.md` | also lists `hygiene-report.md` | this report's existence; package index consistency |
| F6 | `README.md` L8–17 (package index) | listed only `delivery-compass.md`, the audit guide, and a bare `specs/` directory row | §1.6 Documents table: both guides, all four specs, and the promotion log | `mstar-iteration/references/iteration-corpus-hygiene.md` § "Index updates" rule 4 + `iteration-workspace-readme-template.md` |
| F7 | `delivery-compass.md` L21–24 | Scope preamble stated "each is reversed out of a measured defect … not from taste" and then "each is traceable to a measurement" in two sentences | one sentence, same propositions | prose pass; no proposition, number, or citation dropped |

No spec file was edited. The four specs agree with each other and with the compass on every
name they share (§2), so there was nothing on the spec side to correct.

## 2. Shared names verified identical (compass A1–A6 ↔ four specs)

| Name class | Verified spelling | Where |
|---|---|---|
| Check script | `scripts/check_asr_env.py`, run `python3.12 scripts/check_asr_env.py` | compass L112 ↔ spec 01 L25, L70 |
| Recipe doc | `docs/wsl-rocm-gpu.md` | spec 01 L15, L21, L49, L69 (the compass names no doc path, so there is nothing to disagree) |
| Env vars | `HSA_ENABLE_DXG_DETECTION`, `BILI_ASR_DEVICE`, `BILI_KEEP_AUDIO=1`, `BILI_ASR_MODEL`, `BILI_ASR_MODEL_ID`, `BILI_ASR_MODEL_REVISION` | compass L36, L148; spec 01 L74; spec 02 L62; spec 04 L20, L39, L78. Constant naming `ASR_MODEL_ID_ENV_VAR` matches the shipped `ASR_*_ENV_VAR` family (`src/bili_asr/asr.py` L54–59) |
| Provenance keys | `asr_device`, `asr_model_name`, `asr_model_revision`, `asr_vad_segments`, `asr_vad_captured_s`, `asr_vad_captured_ratio`, `asr_low_confidence_at`, `asr_low_confidence_cues`, `asr_mean_confidence` | compass L112, L115–116 ↔ spec 04 L46–56, L65–69, L79–81 |
| Existing `asr_vad_*` family | `asr_vad_model`, `asr_vad_max_segment_s` (from `ASRConfig.vad_model` / `vad_max_segment_s`, `src/bili_asr/asr.py` L154–155) | spec 04 L47 ↔ scope-rationale L75–77; both statements are correct at their own layer (frontmatter family vs config field) |
| Reason codes | seven structural `empty`, `malformed`, `non_monotonic`, `overlap`, `out_of_range`, `identity_mismatch`, `artifact_missing`; seven content `low_confidence`, `leading_mark`, `fragment_cue`, `overlong_cue`, `duplicate_cue`, `repeated_ngram`, `reference_disagreement` | compass L52–53 ↔ `src/bili_asr/quality.py` L15–23 (structural, exact) and spec 03 L21–22 (content). The compass never spells a content code, so it cannot disagree; a reviewer reads them from spec 03 |
| Commands | `bili-asr coverage --quality --archive-root <root>`, `bili-asr asr --bvid <bvid>`, documented batch path `bili-asr run --scope pending [--offline]` | compass L114, L113 ↔ spec 03 L13, spec 02 L49–52, L61 |
| Scripts retired | `scripts/asr_quality.py`, `tests/test_asr_quality_script.py` | compass L114 ↔ spec 03 L15–16; **both deleted at `faebe2d` (20260912-quality-signal-merge Task 3) — the earlier 'present on disk today' note is superseded**; both named in A3's `git ls-files …` check |
| Cue guard paths | `tests/test_asr_cues.py`, `tests/fixtures/asr-cues/`, `tests/fixtures/asr-cues/BV1wLTP6NE9h.p0.tokens.json`, 2037 tokens | compass L117 ↔ spec 01 L87, spec 02 L77–78, spec 03 L89–90, spec 04 L96–98; fixture and token count confirmed in the checkout |
| New config field | `ASRConfig.model_id: str \| None = None`, appended last | spec 04 L21, L78 only (the compass does not name it; no conflict) |

Checked and **not** conflicts: the compass writes `/opt/rocm-<ver>/lib` where spec 01 L37 writes
`/opt/rocm-*/lib` (both version-agnostic placeholders; D1.3 explicitly forbids a pinned
version); the compass says a "second transcript" where spec 03 L52 names the flag
`--reference <path>` (the compass names no flag, so there is nothing to disagree).

## 3. Citation drift — verified, deliberately not edited

The prose-pass constraint froze numbers and citations, so each difference below is reported
rather than rewritten. Every one resolves to the same object; none changes a requirement.

| Citation | Appears at | Ground truth in the checkout | Verdict |
|---|---|---|---|
| `::test_cuda_unavailable_raises_dependency_error_with_rocm_hint` "L330–351" / "(L338–351)" | compass L112; spec 01 L75 | `def` at `tests/test_asr_reproducibility.py` L330, test ends L351 (hint assertions L350–351) | compass range is exact; spec range is a sub-range — same test |
| `::test_fixture_benchmark_reports_only_construction_and_shape` "(L312)" / "(L313–330)" | compass L113; spec 02 L64 | `def` at L312, body L313–328, blank L329 | def line vs body range — same test |
| `REASON_CODES` "(L15–22)" / "(quality.py L15–23)" | compass L114; spec 03 L20 | `REASON_CODES = (` at `src/bili_asr/quality.py` L15, `)` at L23 | both spans contain the seven codes |
| hint rewrite "(asr.py L319–323)" / "L320–322" | compass L30; spec 01 L48 | `raise ASRDependencyError(` L319, message L320–322 | same block |
| env-constant block "(asr.py L56–61)" | spec 04 L20 | constants at `src/bili_asr/asr.py` L54–59 | off by 2; the named constant and the `ASR_*_ENV_VAR` convention are correct |
| exit semantics "README L342" | spec 03 L83 | `README.md` L349 | off by 7 |
| `pilot` documented "`README.md` L118" | spec 02 L34 | `bili-asr pilot --n 20 …` at `README.md` L119 | same command block |
| "operational-sidecars guidance 8/L105" | spec 02 L95 | guidance 8 is L91–96; L105 is guidance 10 | one pair, two targets — ambiguous, prefer naming both |
| "operational-sidecars L115–118" | spec 02 L74 | exit precedence at L117–119 | off by 2 |

Verified accurate, for the record: the spec 03 amendment request quotes
`{KNOWLEDGE_DIR}/architecture-patterns/operational-sidecars.md` guidance 6 at **L80–81**
verbatim; spec 04's `run-scoped-asr-provenance.md` L32 quote is exact; spec 02's L30 quote is
exact; `coordinator.py:494`, `quality.py` L15–23/L87–88/L97/L156/L185–190/L193,
`archive.py` L278/L281–295/L318–321, `asr.py` L129–135/L595–600, `README.md` L44–54/L310/L345
all resolve.

## 4. Cross-document duplication and contradiction

| Check | Result |
|---|---|
| Requirement text in the audit guide (evidence tree) | **None.** A modal-verb scan (`must`, `shall`, `should`, `required`) over `guides/2026-09-12-ten-video-audit.md` returns nothing; §4 is descriptive defect prose with measurements. Left untouched |
| Evidence text in the specs (contract tree) | **By design only.** Spec 01 L39/L60, spec 02 L87, spec 03 L27–31, spec 04 L106–110 carry measurements as decision rationale and cite the guide. Spec 03 L27–31 measures the recorded fixture (95 cues; `low_confidence` 1, `overlong_cue` 2) as the reason `any reason → exit 1` was rejected — a rationale, not a restated requirement. Left untouched |
| Requirement duplicated into the wrong tree | **None found** |
| Compass Scope ↔ specs Contract | Related, not duplicated: the compass states scope + `Evidence:` anchors, the specs state the contract, decisions, and exact names |
| A6 cue-guard boundary repeated in all four specs | **Intentional** per-contract repetition (`asr.py` L125–135 / L447–546, `tests/test_asr_cues.py`, `tests/fixtures/asr-cues/`): each contract is executed by a different plan and each needs its own boundary |
| Point-5 "both halves stay in one point" rationale in compass L78–80 **and** scope-rationale L25–26 | Near-duplicate rationale in two package documents. Not actioned: the compass must stand alone for a reader of the locked scope, and scope-rationale is the traceability home. Flagged for the PM, not moved |
| Compass risk row L205 ("A2 is met on the existing path by documentation plus the printed construction count") vs spec 02 D2.2/D2.3 | Tension, not contradiction: the spec adds no new command (the risk mitigation's condition holds) but does require the existing `asr --pending --limit N` and `pilot` loops to hold one runner. Report only — the mitigation text understates the decided work |

## 5. Corpus hygiene (§1.6) — what was swept

| Tree | Before | After | Action |
|---|---|---|---|
| `{SPECS_DIR}/` | `asr-archive-cli.md` (frozen) + `README.md` | unchanged | **Nothing moved.** No iteration-only draft, scratch, or implementation-pitfall prose sits here. The frozen spec's SenseVoice drift is recorded as an amendment request in spec 04 L112–118 and is left to iteration-close, per the assignment constraint |
| `{KNOWLEDGE_DIR}/` | 6 `architecture-patterns/*.md` + `README.md` | identical 7-file listing, sha256 byte-identical (see §8) | **Nothing moved, nothing added, nothing edited.** No start-chain knowledge addition happened |
| `{ITERATION_DIR}/` root | `README.md` only — no legacy flat `*-delivery-compass.md` / `*-working-guide.md` | unchanged | Nothing to migrate |
| Sibling iteration packages | 9 packages | unchanged | A recursive grep over `.mstar/iterations/` for this iteration's identifiers (`asr-ops-hardening`, `check_asr_env`, `wsl-rocm-gpu`, `BILI_ASR_MODEL_ID`, `asr_vad_captured`) matches only this package and the root index row — no sibling holds this iteration's material |
| `{ITERATION_DIR}/README.md` | had 9 iteration rows | 10 rows | The pre-existing dirty row for this iteration is correct (below) |

**Ambiguous — reported, not moved:** `{SPECS_DIR}/README.md` L30–32 carries a
`{SPECS_DIR}`-scope bullet ("no new `{SPECS_DIR}` file is written during Prepare for
`iter-2026-09-subtitle-transcript-sqlite`"). It is past-iteration process history rather than a
spec index row, but the file's legitimate job is to record supersession and scope decisions, so
moving or deleting it is a judgement call for the PM. Left in place.

**Deliberate non-edit:** the audit guide L100 keeps `bili-asr asr --bvid …`. That is the loop
form the ten-video run actually used, and `specs/02-batch-reuse.md` L87 quotes the line
verbatim in its traceability table; rewriting the guide would break the quote. The compass (the
locked acceptance surface) carries the `<bvid>` placeholder instead — see F3.

## 6. Index rows

`{ITERATION_DIR}/README.md`: **exactly one row** for `iter-2026-09-asr-ops-hardening` (L14),
linking `iter-2026-09-asr-ops-hardening/`, describing the five spec points, status `active`.
Directory-to-row coverage is 1:1 — all ten package directories
(`iter-2026-08-archive-foundations`, `iter-2026-08-corpus-coverage`,
`iter-2026-08-corpus-operations`, `iter-2026-08-live-pc-pilot`,
`iter-2026-08-persistence-scale-safety`, `iter-2026-08-pilot-ops`,
`iter-2026-09-asr-ops-hardening`, `iter-2026-09-bilibili-api-sqlite`,
`iter-2026-09-funasr-nano-7800xt`, `iter-2026-09-subtitle-transcript-sqlite`) have one row
each, and no row points at a missing directory. No row was edited; the new row was already
correct (it is the working tree's uncommitted change from iteration-start).

Two observations the PM may want to settle at lock time, neither a row defect:

- The new row's status is back-ticked (`` `active` ``) while the nine older rows are plain
  words. Cosmetic; left as the PM wrote it.
- Package READMEs exist for 9 of 10 packages; only `iter-2026-09-funasr-nano-7800xt` has none.
  This pass rewrote the new package's README, it did not add one. No index row claims otherwise.

## 7. Findings for the PM (outside writing scope)

1. **The four plan files do not exist.** `{WORKFLOW_DIR}/iter-2026-09-asr-ops-hardening/snapshot.json`
   registers `.mstar/plans/20260912-gpu-enablement-truth.md`, `20260912-batch-model-reuse.md`,
   `20260912-quality-signal-merge.md`, and `20260912-asr-provenance-identity.md`; none is on
   disk anywhere in the checkout or the worktrees. `{PLAN_DIR}` is not mine to write.
2. **The package is gitignored.** `.gitignore` L2 ignores `.mstar/**` and re-includes only
   `.mstar/knowledge/**` and `.mstar/specs/**`, so this package is untracked
   (`git ls-files .mstar/iterations/iter-2026-09-asr-ops-hardening/` is empty). Four of the nine
   sibling packages are tracked (`iter-2026-08-corpus-coverage`,
   `iter-2026-08-persistence-scale-safety`, `iter-2026-09-bilibili-api-sqlite`,
   `iter-2026-09-subtitle-transcript-sqlite`; the last was force-added by its own
   "Phase 1 prepare" commit), the other five are not. The PM's lock commit therefore needs an
   explicit `git add -f` for this package; without it the whole Phase 1 package stays out of
   the commit.
3. **Plan-name drift.** The compass Plans table L89 names plan P4 "Declared model identity +
   VAD capture and low-confidence locations **in provenance**"; the workflow snapshot's `title`
   for the same plan omits "in provenance". The compass wording is the more precise one; the
   snapshot is engine state, so this is a registry fix, not a prose fix.
4. `snapshot.json` still reads `"phase": "phase-1-prepare"` while the engine status block
   reports `transition: phase-2-execute` / `gate: PASS`.

## 8. Evidence

- **Touched files (3).** Package mtimes pin exactly `delivery-compass.md`, `README.md` (package
  index), and `guides/hygiene-report.md` (new) to this pass; the other six package files keep
  their pre-pass mtimes, i.e. the two guides' evidence text and all four specs are untouched.
- **`git status --short`** on the tracked tree reports only `.mstar/iterations/README.md` (M) and
  `.mstar/status.json` (M) — both pre-existing iteration-start changes, neither made here. **None
  of this pass's edits appear there**, because finding 7.2 ignores the package.
- **No knowledge addition.** `{KNOWLEDGE_DIR}` and `{SPECS_DIR}` are tracked, so their absence
  from `git status --short` is itself proof: the tree still holds 6 knowledge docs +
  `README.md` and 2 spec files, and every one of those 9 files hashes identically before and
  after this pass (listing in the completion report).
- **Nothing was renamed or moved between trees**, so no inbound link needed repairing; the two
  cross-tree references this package gained (`README.md` → `guides/hygiene-report.md`, compass
  L214 → `guides/hygiene-report.md`) resolve inside the package.
