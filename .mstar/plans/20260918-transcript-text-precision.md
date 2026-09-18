# Transcript text precision: cue-writer Latin spacing, and the hotword benefit measured

> **For agentic workers:** REQUIRED SUB-SKILL: Use `mstar-sdd` (recommended) or inline execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the cue writer from gluing Latin words together inside a cue, and settle **by measurement** whether the six Chinese homophone hotwords added on 2026-09-17 do what they were added for — measuring both the benefit (each term against its measured homophone, arm against arm) and the cost (identical-character ratio, cue count, `asr_mean_confidence`, `asr_low_confidence_cues`). An inert result is a result: it keeps `R3` open with the counts instead of claiming a benefit the measurement does not show.

**Closes:** `e2e-23191782-season-7686105 · R3` (compass criterion **1**, renumbered from 2 on 2026-09-18) — **closed 2026-09-18** on this plan's A/B measurement. The other row this plan was chartered with, `· R6` (the cue-writer space rule), is **NOT closed**: Task 1 was retired on evidence at its own authorised Step-1 exit and the entry stays open — see `## Task 1 disposition`. One further row follows from this close: the five hotwords the A/B did not exercise are registered as `20260918-transcript-text-precision · R1`. Compass: `{ITERATION_DIR}/iter-2026-09-text-and-ledger-precision/delivery-compass.md` `## Acceptance Criteria`.

**Architecture:** `_token_cues` assembles each cue's text with `text = _clean_text(pending + "".join(parts))` (L765), while the space-repair rule lives in `_join_text` (L700-718) — called from exactly two places, `hand_back()` (L760, returning a closing mark) and the undersized-cue absorption path (L776). Intra-cue concatenation is the third place that *looks* like it needs the rule, and R6 was registered on that reading.

**It is not the same situation, and the difference is measured.** At the append site the pieces are model *shards*, and two adjacent ASCII-alphanumeric shards are far more often **one word split up** than two words whose separator was lost. The fixture carries exactly **8** token boundaries where `_join_text`'s character-class condition fires, in four words: `trib`+`unal` (1), `t`+`oken` (2), `deep`+`se` and `se`+`ek` (twice over, for two occurrences of `deepseek`) and `N`+`GO` (1). Applying `_join_text` per token was measured on the pinned fixture (2026-09-18, in-memory copy of `asr.py`, no file edited): cue count (95) and timings identical, but **4 of 95 cues changed, every change a space inserted inside a single Latin word** —

| cue | today (correct) | character-class rule |
|---|---|---|
| 3 | `这个什么 tribunal点 org` | `这个什么 trib unal点 org` |
| 35 | `token怎么来弄？` | `t oken怎么来弄？` |
| 38 | `转会差对于我们来讲也挺多的，那种deepseek deepseek好便宜，token是好便宜的。` | `转会差对于我们来讲也挺多的，那种deep se ek deep se ek好便宜，t oken是好便宜的。` |
| 56 | `你比如说我我已经on the list了，所以我没有办法去怎样，我没办法靠我自己去成立一个这个NGO，但是你也不妨碍我们` | `你比如说我我已经on the list了，所以我没有办法去怎样，我没办法靠我自己去成立一个这个N GO，但是你也不妨碍我们` |

The token stream cannot distinguish the two cases: at `t`+`oken`, `N`+`GO` and `deep`+`se` the second shard carries **no** leading space and the first ends in an ASCII alphanumeric, so the boundaries are indistinguishable from `ME` in the corpus's `asME IDEA` (e2e report, Defect 1) — while at `trib`+`unal` it is the *first* shard that carries the space (`" trib"`), and `_join_text` fires on the pair's `b`/`u` edge anyway (raw `" tribunal"` → `" trib unal"`, exactly one inserted space), so the condition splits a word that was already correctly spaced. What *can* distinguish them is the model's own recognised text, which `normalize_result` already receives beside the timestamps (`item["text"]`, read at L844; the token stream it feeds the shaper is read at L838): on the pinned fixture that text contains `tribunal`, `deepseek`, `token`, `NGO` — the joined forms, each exactly once or twice — while it carries the space in the corpus's glue cases. So the rule becomes two conditions, both required: the character-class condition (`_join_text`'s own rule — the single definition, reused, never forked) **and** the model's text containing the separator at that boundary. Measured on the same fixture with that rule: **95 cues, byte-identical to today**, and on a synthetic shard stream (`as`,`ME`,` IDEA` with text `as ME IDEA`) `asME IDEA` → `as ME IDEA`; Chinese and shard words (`tribunal`, `NGO`) untouched.

Task 2 is a measurement, not a code change: the six Chinese homophone hotwords were added on measured *errors* (118 mis-renderings across the season archive) and their *benefit* is still unverified — the register entry's own target prescribes re-transcribing one affected lecture with and without them.

**Tech Stack:** Python 3.12, pytest, the repo's fixture-driven cue tests, the operator's GPU archive host via the existing `ab.sh` harness.

**Execution:** mstar-sdd

**Main worktree branch**: `main`

## Global Constraints

- **Every command in this plan names its working directory.** Python and pytest run from the **package
  root** `/root/workspace/bilibili-asr-archive/bilibili-asr-archive` (where `.venv/`, `src/`, `tests/`
  live): `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-transcript-text-precision/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest …`.
  `git` runs from the **repository root** `/root/workspace/bilibili-asr-archive`. The form
  `bilibili-asr-archive/.venv/bin/python -m pytest tests/…` is runnable from neither root.
- **Test invocation on a feature worktree (binding — learned the hard way in the previous
  iteration, then re-verified): the worktree has no `.venv`**, and the control-root venv's editable
  install resolves `bili_asr` to the **control-root** `src`. A run written as
  `cd <repo>/bilibili-asr-archive && .venv/bin/python -m pytest` therefore either fails or silently
  grades the **unmodified** tree and produces false evidence in both directions. Every run must be:
  `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-transcript-text-precision/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest <selector> -v`
  and must confirm `bili_asr.__file__` resolves **under the worktree** before any result is believed.
  Captured durably in `{KNOWLEDGE_DIR}/architecture-patterns/worktree-test-invocation.md`.
- Python 3.12; the only interpreter used is the repo venv (`.venv/bin/python` from the package root).
- **The existing pinned cue fixture must stay byte-identical**: `tests/fixtures/asr-cues/BV1wLTP6NE9h.p0.tokens.json` and the expectations in `tests/test_asr_cues.py` are the regression anchor for the shaper. The change must not insert a space where the model already supplied one, must not alter Chinese text, and must not change cue boundaries, counts, or timings. This is a hard gate **and a regression guard — not evidence for the rule** *(corrected 2026-09-18; the stronger reading stood here and in the self-review until the disposition below retracted it)*: the two-condition rule was measured against this exact fixture at 95 cues and left them byte-identical, but only because the fixture's 91 inserted spaces sit at **0** firing boundaries, so the fixture cannot exercise the repair at all. A candidate rule that changes any of those 95 cues is wrong, not a fixture to update.
- **The separator decision is anchored to the model's own recognised text**, never inferred from character classes alone: `item["text"]` is the second input the shaper needs, and `_join_text` stays the single definition of the *separator itself* (called, not reimplemented). If the recognised text is absent or the boundary cannot be located in it, the model's own token string wins — the rule may only ever add a separator the text already contains.
- The character-count measurement that decides cue boundaries (the `_CUE_MAX_CHARS` ceiling at L817, `formed()` at L747-751, the absorption test at L771) keeps using the raw `"".join(parts)`: only the *emitted* text is repaired, so boundaries, counts and timings are untouched by construction. A cue may therefore exceed `_CUE_MAX_CHARS` by the few separator characters, exactly as the absorbed-fragment path already may (L773-775 documents that trade-off); the `overlong_cue` reason is an advisory content code, not a defect.
- Task 2 **must not add, remove, or reorder** `DEFAULT_HOTWORDS` in a committed change. The "without" arm is produced by a temporary, uncommitted edit that is restored before the task closes; both arms are proven from the produced artifacts, never from the invocation.
- Verification scope follows `mstar-harness-core` § 定向执行与验证边界: only changed behaviour and direct contracts; no local full-suite runs without explicit permission.
- Task 2 runs **one** real-host GPU transcription A/B (two arms, same audio). This is a local decoding-configuration measurement on the operator's own archive host — **not** browser/device/installed-deployment E2E, and no such scenario is a task or gate of this plan. If the host or model cache is unavailable, record the measurement as not-run rather than claiming it passed.

## Engine lifecycle

Who advances this plan row's engine state, and what records each transition:

- **Scoped sequence** — one engine verb per transition; never a hand-edited snapshot: `bind --coordinator` → `prepare` → `bind` → `progress` → `handoff` → `accept` → `integration-start` → Git merge → `integration-accept` → `complete`.
- **Evidence order** — `compound` disposition, PR identity and merge evidence are recorded **after** the row is `Done`; the engine refuses those writes while any plan row is not `Done`. The delivery tail runs on a completed row, never ahead of it.
- **Snapshot declares no integration anchors** → the row cannot reach `Done` today: stop at a submitted/accepted handoff, report the blockage to the coordinator, and never fabricate a terminal state (`Done`, `completed`, PR identity, merge record).

Semantics and failure behavior → `mstar-artifacts/references/plan-workflow-lifecycle-contract.md`; PM step sequence → `mstar-roles/references/project-manager/plan-management.md`.

---

### Task 1: Apply the space rule inside a cue

**Effort (agent-oriented):** M

**Split point:** The measurement (Step 1) and the change (Steps 2–5) are separable: Step 1 alone answers whether the recognised text carries the separators, and if it does not, this task stops there and returns to the PM with the measurement — the shaper must not be changed on a rule the data does not support. If Step 1 confirms, Steps 2–5 close in one round.

**Files:**
- Modify: `bilibili-asr-archive/src/bili_asr/asr.py` (`_token_cues`'s assembly at L765 and its signature; `normalize_result`'s call site at L840 — the sole call site, inside the `isinstance(tokens, list)` branch whose `item` already carries `text`; the character-ceiling measurement at L817 and `formed()` at L747-751 stay on the raw join)
- Test: `bilibili-asr-archive/tests/test_asr_cues.py` (new cases + the existing pinned-fixture case must stay green), fixture added under `bilibili-asr-archive/tests/fixtures/asr-cues/`
- Out of scope: `_join_text` itself (its rule is correct and stays the single definition of the separator), Chinese-text behaviour, cue boundaries/timings, `_CUE_*` constants, the token loop's control flow (only the text assembly changes).

**Interfaces:**
- Consumes: `_join_text(left, right)` — the existing rule "insert one space iff both sides are ASCII alphanumeric"; `item["text"]` — the model's verbatim recognised text, already read by `normalize_result` (L844) and present in the pinned fixture's payload (`[0]["text"]`, 2 193 characters beside 2 037 timestamp entries, whose `token` strings join to 2 102 characters).
- Produces: a `_token_cues(tokens, recognised_text)` whose cue text carries the model's own separator wherever `_join_text`'s condition holds **and** the recognised text shows that separator; consumed by every downstream artifact (txt/md/srt are all rendered from the same segments). The pinned fixture's 95 cues stay byte-identical.

- [ ] **Step 1: Measure before changing (this step can end the task)**

Read the recognised text and the timestamp stream of the pinned fixture together and record, in the task report: (a) that the concatenated token strings are **not** the recognised text (2 102 vs 2 193 characters — the text carries separators the token stream drops); (b) for each of the shard boundaries (`trib`+`unal`, `deep`+`se`+`ek`, `t`+`oken`, `N`+`GO`), whether the recognised text contains the joined or the spaced form; (c) whether any boundary in the fixture has the spaced form (i.e. whether the fixture exercises the repair at all). Measured at plan-review time (2026-09-18): all 8 firing boundaries in the fixture carry the **joined** form in `item["text"]` — `tribunal`, `token`, `deepseek`×2, `seek`×2, `NGO` — so the fixture does **not** exercise the repair, and the positive case is pinned by the synthetic test below rather than by the fixture. If the recognised text shows **no** spaced boundary anywhere and the corpus case cannot be reproduced from the material this plan may read, stop and return to the PM: the mechanism is unsupported by the data, and R6's closure must say so rather than land a rule that splits words.

- [ ] **Step 2: Write the failing unit test (plus its guard)**

Token entries are dicts with `token` / `start_time` / `end_time` / `score` (the shaper skips anything that is not a dict, L786-793 — a tuple stream yields zero cues):

```python
def test_a_missing_separator_is_restored_from_the_recognised_text() -> None:
    """The model's own text carries the separator the token stream lost."""
    tokens = [{"token": "as", "start_time": 0.0, "end_time": 0.4, "score": 0.9},
              {"token": "ME", "start_time": 0.4, "end_time": 0.9, "score": 0.9},
              {"token": " IDEA", "start_time": 0.9, "end_time": 1.4, "score": 0.9}]
    assert _token_cues(tokens, "as ME IDEA")[0]["text"] == "as ME IDEA"


def test_a_word_split_into_shards_is_not_spaced() -> None:
    """Two shards of one word are not two words: the text says 'tribunal'."""
    tokens = [{"token": " trib", "start_time": 0.0, "end_time": 0.4, "score": 0.9},
              {"token": "unal", "start_time": 0.4, "end_time": 0.9, "score": 0.9}]
    assert _token_cues(tokens, "tribunal")[0]["text"] == "tribunal"
```

Only the **first** of the two is failing today (measured 2026-09-18 on the current shaper: `_token_cues(tokens)` → `'asME IDEA'`). The second is a **guard**: it already passes before the change (`_token_cues(tokens)` → `'tribunal'`, correct at one argument because the shards' leading space is preserved in the raw join) and its job is to stay green once the recognised text is threaded in — it is the assertion that the two-condition rule does not start splitting shard words in the very shape the plan sets out to protect. "Expect FAIL" in Step 3 therefore applies to the new separator case; the shard case must pass both before and after, and a run that shows it failing means the implementation is wrong, not the test.

- [ ] **Step 3: Run tests — expect FAIL**

Run: `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-transcript-text-precision/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_asr_cues.py -k "separator or shards" -v`

- [ ] **Step 4: Minimal implementation**

At the assembly site (L765) fold the pieces through `_join_text` — the rule is called, never reimplemented — but only where the recognised text confirms the separator at that boundary; everywhere else keep the model's own string. Nothing else in the shaper moves: the length/ceiling measurements (L747-751, L771, L817) keep using the raw `"".join(parts)` so boundaries, counts and timings cannot move, and the emitted text is what changes. Pass the recognised text in from `normalize_result` (L840), which already has `item.get("text")`; a caller that supplies none gets today's behaviour, which is the honest fallback rather than an optional feature.

- [ ] **Step 5: Run the new cases AND the pinned-fixture case — expect PASS**

Run: `cd /root/workspace/bilibili-asr-archive/.worktrees/20260918-transcript-text-precision/bilibili-asr-archive && PYTHONPATH=$PWD/src /root/workspace/bilibili-asr-archive/bilibili-asr-archive/.venv/bin/python -m pytest tests/test_asr_cues.py -v`

The pinned asr-cues fixture must be unchanged, byte for byte: `cd /root/workspace/bilibili-asr-archive && git diff --stat -- bilibili-asr-archive/tests/fixtures/asr-cues/` must print nothing.

- [ ] **Step 6: Commit**

### Task 2: Measure the six Chinese homophone hotwords (A/B)

**Effort (agent-oriented):** M

**Split point:** Arm 1 and Arm 2 are separate runs; if only one arm lands in a round, record it as half the measurement and finish the other next round — never compare against the season run's numbers as if they were this A/B's other arm.

**Files:**
- Create (target host, scaffolding — **not** the repository): an A/B driver beside `/root/e2e-asr/tools/ab.sh`, reusing its shape (two fresh archive roots, one seeded row each, sequential runs, a comparison mode). Confirm the host preconditions in Step 1 before relying on either path.
- Create (repository, iteration package): `{ITERATION_DIR}/iter-2026-09-text-and-ledger-precision/guides/hotword-ab-20260918.md` — the comparison, the arm readbacks and the decision (Step 6).
- **Not** modified by this task: `{PROJECT_DIR}/_default/residuals.json`. Step 6 reports the decision and cites the guide; the register write is the PM's domain operation, not a leaf's.
- Out of scope: `DEFAULT_HOTWORDS` content (no committed change), the previous A/B's roots (`/root/e2e-asr/ab-hotwords/{new,old}`), the season archive.

**Interfaces:**
- Consumes: the season manifest row `BV1H69sB6EeF:p0` (cid `37953865549`, 6870 s) as the seeded row for both roots; the GPU venv + `HSA_ENABLE_DXG_DETECTION=1`; the repaired `{REPO}/.env` as the credential source; the six terms at `asr.py` L180–185.
- Produces: two transcript bundles for the same audio whose md `asr_hotwords` fields differ by exactly those six terms, plus the comparison — benefit counts **and** the cost side (identical-character ratio, cue count, `asr_mean_confidence`, `asr_low_confidence_cues`) — that either closes `R3` or keeps it open on the counts (compass criterion **1**, renumbered from 2 on 2026-09-18). A single arm is half a measurement and does not close anything; the season run's numbers are not the other arm.

- [x] **Step 1: Build the two roots and both arms**

First confirm the host prerequisites with one command each, and record the outputs — the A/B driver lives on the operator's archive host, not in this repository, so its presence is a precondition, not an assumption: `test -x /root/e2e-asr/tools/ab.sh` and `test -d /root/e2e-asr/ab-hotwords`. If either is missing, write the driver (Files: Create) before running an arm, or record the measurement as not-run — never run a single arm and call it the measurement.

Arm **with** = the current default list (33 entries, the six included). Arm **without** = the six temporarily removed from `DEFAULT_HOTWORDS` (uncommitted, restored immediately after the run). Seed both roots from the season manifest row with `status: needs_audio` — the archived part's audio was reclaimed by design, so each arm re-downloads it (≈35 MB, ≈17 min decode at the measured rtf ≈ 0.15).

- [x] **Step 2: Prove the arms from their artifacts, not from the invocation**

Read `asr_hotwords` out of each arm's md frontmatter and diff the two strings: the difference must be exactly the six terms, and the working tree must be clean after the runs (the temporary edit is gone): `cd /root/workspace/bilibili-asr-archive && git status --porcelain` (repository root; no output means clean).

- [x] **Step 3: Measure the primary question**

For each of the six terms, count the correct form and its measured homophone in each arm's txt: `扬弃` vs `阳气`/`洋气`, `自在` vs `子在`, `变易` vs `变异`, `此在` vs `次在`/`词在`, `感性` vs `感兴`, `实存` vs `时存`. Report both arms side by side with absolute counts. The pairs are not free inventions: they are the term/homophone table the season run measured, recorded in `src/bili_asr/asr.py` L156-161 (and, for five of the six, in the e2e report's transcript-quality table) — cite that block so a reader can check the pairing without re-deriving it.

- [x] **Step 4: Measure the cost side**

For both arms: identical-character ratio between the two transcripts, cue count, mean confidence (`asr_mean_confidence`), and low-confidence cue count (`asr_low_confidence_cues`) — the removal decision needs the harmlessness evidence, not just the benefit.

- [x] **Step 5: Decide per the rule fixed before the run**

- **Confirms the entries** (correct forms rise and homophones fall in the "with" arm, global difference ≤5 %): report "close `R3`", citing both arms.
- **Inconclusive** (no material difference): report "keep `R3` **open**" and record that the entries are inert on this evidence — do not claim a benefit the measurement does not show.
- **Refutes the entries** (the "with" arm is worse, or the difference is dominated by new damage): recommend removal to the PM; that is a separate product decision, not this task's change.

- [x] **Step 6: Record the comparison; report the decision (the PM closes the register)**

Append the comparison (raw counts + the `asr_hotwords` readback) to `{ITERATION_DIR}/iter-2026-09-text-and-ledger-precision/guides/hotword-ab-20260918.md`, then **report the Step 5 decision to the PM with that file cited**. Do **not** edit `{PROJECT_DIR}/_default/residuals.json`: the register is the PM's write domain — a child Assignment inherits its task scope, not the coordinator's register authority. The PM closes or keeps `e2e-23191782-season-7686105 · R3` in place on the strength of that file.


## Task 1 disposition — BLOCKED on evidence, moved out of scope (2026-09-18)

Task 1 returned `NEEDS_CONTEXT` at its own authorised Step-1 exit, with a finding the plan did not
anticipate. The plan's stop clause is a conjunction — *no spaced boundary in the fixture* **and** *the
corpus case not reproducible*. The implementer verified **both** conjuncts rather than assuming the
second:

1. Token join = 2 102 chars vs recognised text = 2 193 — confirmed.
2. All 8 `_join_text`-firing boundaries carry the **joined** form (`tribunal`, `token`, `deepseek`×2,
   `NGO`); none carries the spaced form.
3. **Beyond the brief:** all **91** inserted spaces in the fixture were cross-tabbed against the token
   boundary map — **0 of 91 sits at a firing boundary**. The fixture therefore contains no positive case,
   and the "95 cues byte-identical" measurement is **near-vacuous** for this rule: it shows only that the
   rule inserts nothing there, not that it repairs anything.
4. **The decisive finding:** the corpus case cannot be replayed. The archived payload's keys are
   `['segments', 'source', 'provenance']` — it stores the **output** of the very line this task would
   change, with no `timestamps` and no `text`. So the rule's second condition *cannot be evaluated on the
   corpus at all*, and the only positive case available is a synthetic one the implementer would author —
   i.e. the rule would be closed against a case it has never been shown to handle.
5. Compounding: the corpus cue glues at **three consecutive boundaries**, exactly where locating a
   boundary in `item["text"]` is least reliable. The plan's risk note conceded the absent-text fallback
   but not boundary *location* under consecutive glue.

**PM decision:** do **not** land the rule. Task 1 is moved out of this iteration's scope; `R6` stays
**open** in the register with the unblock recorded (retain a raw Nano payload carrying both `timestamps`
and `text` for a glued cue — either recovered or captured on a re-run; a narrowed whole-cue-text rule is
the alternative, and it is a settled-design change). This plan therefore closes **`R3` only**; `R6`'s
companion criterion is retired in the compass with the reason.

**Evidence value, corrected:** this plan previously treated the pinned fixture's byte-identity as
evidence *for* the repair. It is a **guard against regression**, not evidence for the rule — stated here
so a later reader does not inherit the stronger claim.

## Plan self-review (PM before locked)

1. **Spec coverage:** `R6` → Task 1; `R3` → Task 2. Both register entries have a closure or keep-open path with named evidence. Task 1's Step 1 can end the task with a measurement instead of a change, and that outcome is a valid one: the register closure then records that the rule the shaper would need is not supported by the data this plan may read.
2. **Placeholder check:** Task 1 names the exact function, the exact assembly line, the fixture path, the second input the shaper needs, and runnable selectors with their working directories; Task 2 names the exact seeded row, cid, duration, the artifacts that prove each arm, all six term/homophone pairs with the source of the pairing, the host preconditions and a pre-written decision rule. No `TBD`/`etc.` remains.
3. **Type consistency:** `_token_cues` / `_join_text` / `_clean_text` / `normalize_result` are the module's real names and the token entries' real keys (`token` / `start_time` / `end_time` / `score`) are the ones the shaper reads (L789-793); `asr_hotwords` / `asr_mean_confidence` / `asr_low_confidence_cues` are the real frontmatter keys; the six terms are at `asr.py` L180-185 and the default list holds 33 entries.
4. **Capacity (task shape / session fit):** Task 1 is M with a declared split point (measure, then change) and its two-condition rule was measured against the pinned fixture before the plan was locked, so the regression gate is known-satisfiable rather than hoped-for. *(Corrected 2026-09-18: "satisfiable" is the whole of what that measurement showed — the fixture sits at 0 firing boundaries, so the gate guards against regressions and is not evidence for the rule; see `## Task 1 disposition`.)* Task 2 is M with a declared split point (one arm per round) and its two-arm requirement is the whole point of the task — budget pressure must not collapse it into a single arm compared against stale numbers.

## SDD runtime (ephemeral)

When using `mstar-sdd`, artifacts live under `{SDD_DIR}` (see `mstar-conventions`). Do not duplicate briefs/reports in this file.

## Review Gate Summary

Durable decision surface — sufficient for handoff once `{SDD_DIR}` is gone.

- **Decision:** `Approve` (plan QC tri-review → targeted re-review → bounded confirmation)
- **Review range / Diff basis:** `0fc963d271e8497b473b2b08ff6ea653085a0ebd..0fc963d271e8497b473b2b08ff6ea653085a0ebd` — **no product diff exists**: the branch tip equals BASE, the branch carries 0 commits, `review/branch.diff` is 0 bytes, and the seats were told that is the reviewed fact. The reviewed surface is this plan's **document + register state** (plan, compass, the A/B guide, the L2 review, the SDD ledger, the register rows).
- **Review bundle:** `{SDD_DIR}/review/` — `qc-consolidated.md`, `qc1.md`, `qc2.md`, `qc3.md` (ephemeral; gitignored).
- **QC inputs:** `qc1.md` / `qc2.md` / `qc3.md`. Wave 1 (`Request Changes`: 6 distinct Warnings, 13 distinct Suggestions) → fix wave → wave 3 targeted re-review of the two raising seats (`Approve` each) → wave 4 bounded confirmation of the post-revalidation edits (`confirmed`). `qc-specialist-3` approved in wave 1 and was not re-dispatched.
- **Task reviews:**
  - Task 1 — **not completed; retired on evidence.** Implementer returned `NEEDS_CONTEXT` at its own authorised Step-1 exit; no change was made and no review was owed. Recorded in `## Task 1 disposition` and in the compass `### Scope changes`; `R6` stays **open**.
  - Task 2 — review range `0fc963d..0fc963d` (no repository change), earned **`Task quality: Approved`**, report `task-2-review.md` → `{SDD_DIR}/task-2-review.md`. Its 12 host-side `⚠️ Cannot verify` items were resolved by the PM with read-only reads on the archive host, recorded in `{SDD_DIR}/progress.md`.
- **Blocking result:** **fixed** — all 6 Warnings fixed in PM-owned artifacts (guide fixes dispatched to a `writing-specialist` wave; compass/plan/register by the PM). No blocking item was deferred.
- **Residual findings:** no open `R#` from this plan's QC wave. Two rows exist for this `plan_id`:
  - `R1` — five of the six Chinese homophone hotwords' *benefit* remains unverified (the A/B exercised only `扬弃`); severity `low`; `decision: defer`; owner `@project-manager`; **tracking:** register `entries["20260918-transcript-text-precision"]`; **not** a blocker-defer (it is a known-unknown with a named trigger, not a blocked dependency).
  - `R2` — the frozen implementer report's `14:30:xx` / `14:51:xx` cells; severity `low`; `decision: accept`; `lifecycle: waived` (closed on entry, with reason and re-open trigger). **Tracking:** same register group.

## QA Gate Summary

Filled at the QA gate; see the row below for the acceptance trace pointer and the result.

- **QA gate:** `mandatory` · **QA mode:** `acceptance-only`
- **QA gate reason:** `open R# on this plan_id` (successor `R1`) — the matrix's residual row forces the dispatch even though this plan ships no runtime diff.
- **QA verdict:** `Approve with residuals` — all 8 assigned ACs pass; 0 blocking findings.
- **Acceptance trace:** `{SDD_DIR}/review/qa.md` — AC → evidence → result mapping, with the coverage/gap disclosure and the report's four `⚠️ Cannot verify` channel limits.
- **Evidence reused vs newly run:** all acceptance evidence was **reused** (guide, register, plan, compass, L2 review, SDD ledger, QC bundle, the PM's host capture); newly run were read-only static checks only — `git rev-parse/rev-list/diff --stat/status --porcelain/hash-object`, `sha256sum`, `wc -c`, and two read-only `python3` comparisons (register field/enum/lifecycle audit; guide §12.1–12.2 vs the host capture). **No tests, no build, no GPU A/B re-run, no network/host access.**
- **R# closure recommendations:** `e2e-23191782-season-7686105 · R3` — verified close **stands** (`resolved`, 2026-09-18; schema-consistent with its closed sibling; the refusal clauses intact). `20260918-transcript-text-precision · R1` — **keep open** (`defer`, low; scope + target/trigger + owner + the product-side wording sync all present; Durable Roadmap ⑤). `20260918-transcript-text-precision · R2` — **keep waived** (`accept`, low; reason + re-open trigger present; no fix claimed). Register arithmetic re-verified: open = **medium 1 / low 7**.
- **QA findings:** F1 `nit` and F2 `low`, both non-blocking one-line PM fixes — **both applied** (F1: the consolidated's wave attribution corrected; F2: this plan's `R3` evidence now cites the guide's digest instead of its pre-wave byte count). No re-review wave was required and neither was registered as a residual.

## Done note — how this row reached `Done` (2026-09-18)

The plan's `## Engine lifecycle` section records that its scoped sequence is *one engine verb per
transition*, and that with no integration anchors declared the row was not expected to reach `Done` on
that route. Both facts still hold in this session, and both are stated here rather than papered over:

- **What was executed:** the full gate set, in order — per-task L2 review (Task 2 `Approved`; Task 1
  retired on evidence with no change to review), plan QC tri-review ⇒ targeted re-review ⇒ bounded
  confirmation (**`Approve`**, 0 Critical / 0 Warning open), and the mandatory QA gate
  (**`Approve with residuals`**, all 8 ACs pass). Records: `{SDD_DIR}/review/qc-consolidated.md`,
  `{SDD_DIR}/review/qa.md`.
- **What was NOT available:** the engine verbs themselves. This host has no `mstar` CLI and no importable
  engine package, so no `bind/prepare/progress/handoff/accept/integration-*/complete` sequence could run
  for this row. The `Done` status was therefore recorded through the CLI-less legacy route (the same
  route `mstar-sdd` sanctions for ledger progress when the CLI is absent), with the workflow snapshot and
  this plan's compass row as the carriers.
- **What is deliberately NOT claimed:** no PR identity, no merge record, and no per-row integration
  anchor is fabricated for this row — `Done` here is the plan-row state (the iteration's execute +
  review/acceptance stage complete, per the lifecycle contract's "row `Done` is not workflow
  completion"), not a delivery claim. The iteration's own tail (`iteration-close` → PR delivery →
  verify merge) owns delivery, and that obligation is unchanged.
- **Carried forward for the coordinator:** with the engine unavailable, the iteration's `phase-3-close`
  transition and every later stage must be advanced the same way — by recorded gate evidence plus
  explicit snapshot writes — or the CLI must be present. That is a real limitation of this session's
  environment, not a property of the plan.
