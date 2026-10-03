# Architect decisions — iter-2026-10-asr-success-attestable

## D8 — shortfall: block or mark?

**Mark — keep the transcript, refuse the success word.** Write `outcome=stored-short` +
`error_code=coverage-shortfall` alongside the coverage pair. Blocking is wrong twice over: the
transcript is the expensive artifact and a partial one is still evidence, and discarding it leaves
the next run nothing to improve on.

Two end states, no third: *covered* = evidence present ∧ `coverage ≥ 0.97` ∧ `stored`; *short* =
evidence present ∧ `coverage < 0.97` ∧ `stored-short`. `stored` with no evidence is the state D9
abolishes. A re-run upgrades outcome and evidence together or stays short — an old unqualified
success cannot be laundered, since the evidence travels with the record and can only move up. Stock
is not rewritten: old rows read as *not evaluable*, never repaired in place.

## D9 — coverage evidence: quantity, threshold, placement

**Granularity: one span per part, not per chunk.** A per-chunk census compares chunks against the
very tiling that produced them and misses the observed defect — the failing chunk *did* emit text,
just far less span than it owed. Compared quantity: the run's **produced span** against the
**decoded duration of what that run actually fed the model**.

- `decoded_s` = `sum(len(chunk) / SAMPLE_RATE)` over that run's `_split_audio` output — a *measured*
  quantity, not a header guess; exactly what `AudioDecodeError` admits is missing today.
- `produced_s` = `max(cue.end) − min(cue.start)` — span, not span-sum, so duplicate or overlapping
  cues cannot inflate coverage.
- `coverage = produced_s / decoded_s`; shortfall iff `coverage < COVERAGE_MIN`. Detection only: never
  aborts the run, never suppresses the write.

**Threshold from the basis, not a round number.** Measured pair: `decoded_s = 73.561` /
`produced_s = 59.0` ⇒ `coverage = 0.80204…`. The defect must fall strictly below and normal output
strictly above, so the threshold lies in `(0.803, 1.0)`; take **`COVERAGE_MIN = 0.97`**. Biased high
because a false shortfall flag on a real success costs more than a narrow band: it absorbs the
sub-second edges a correct run loses (VAD lead-in, trailing silence, cue-end rounding) while still
flagging any loss past ~3%, including a truncated final chunk that a round `0.9` would sail past.
`1.0` is rejected — harmless arithmetical tails would flag. Keep the basis beside the constant so a
retune argues from `0.80204` instead of re-inventing it.

**Tiling promise: usable as the denominator's definition, not as a probe.** "Lengths tile the input
exactly" makes `sum(chunk len)` exactly the decoded sample count, so `decoded_s` needs no tolerance
band — and it keeps the failure *attributable*: on a fresh decode that tiles, the missing span was
dropped by the model, not the split. It is a promise, not a checked invariant, so it cannot be
asserted at read time for rows already written; it defines `decoded_s` for new runs only.

**Recorded in the part's manifest row, not a sidecar:** `decoded_s`, `produced_s`, `coverage`
(compared unrounded), `coverage_min` — beside the existing `outcome`/`error_code`. In-row survives
worktrees, re-reads and archive tooling; a sidecar can drift from the transcript it describes.
**Consumers:** the `asr.py` writer; re-runs (re-measure, never copy a prior `coverage`); the
read-only audit path (the only consumer that can speak for pre-existing rows, and only to say *not
evaluable*); any coverage-aware view needing covered-vs-short; manifest/summary output, so
`stored-short` is never counted as success.

## D10 — caption exhaustion: the shape

**Choice: (b) — record the cause distinguishably — plus corroboration for the indefinite case.**
(a) alone is unsound: the control part answered `tracks=0` on three probes and is genuinely
caption-less, so if emptiness stopped counting as exhaustion that part would be permanently denied
the paid branch — the exact preservation case. The defect isn't that emptiness was believed; it's
that two *kinds of evidence* were funnelled into one indistinguishable record
(`_record_captionless_part(..., "not_found", ...)` vs `(..., None, ...)`) and read as one outcome. A
gateway `not_found` is a *definite* negative; an empty inventory is *indefinite* — the gateway
contract says so verbatim ("An inventory the credential in effect could not see is an empty tuple"),
so an empty tuple must not be treated as absence on one look.

So the record splits by cause — `not_found` and `no-language-match` definite, `inventory-empty`
indefinite — and the view reads them differently: definite admits at once, indefinite only at
`CAPTION_EMPTY_CONFIRMATIONS = 2`. Why 2, not 3: 1 is demonstrably wrong (`I-000187`), 2 is the
smallest count that can separate the cases at all, and 3 is merely what one control happened to
reach — probe count is an operator knob, and baking one control's count in would encode an anecdote
as an invariant. No rescan: only new attempts carry codes.

Replace only the outcome test; the existing `subtitle_attempts` CTE (newest per `video_part_id` by
`finished_at DESC, run_id DESC`, `kind='subtitle'`, `recency = 1`) and every other guard stay as is.

```sql
-- NEW CTE: independent observations of an indefinite negative.
, empty_inventory_confirmations AS (
    SELECT video_part_id, COUNT(DISTINCT run_id) AS confirmations
    FROM subtitle_attempts
    WHERE kind = 'subtitle' AND outcome = 'no-subtitle'
      AND error_code = 'inventory-empty'      -- NOT NULL: an unknown code is not a confirmation
    GROUP BY video_part_id
)
-- plus one LEFT JOIN in the outer query:
LEFT JOIN empty_inventory_confirmations AS eic ON eic.video_part_id = vp.video_part_id

WHERE vp.processing_status <> 'gone'
  AND NOT EXISTS (SELECT 1 FROM transcripts AS t WHERE t.video_part_id = vp.video_part_id)
  AND NOT EXISTS (SELECT 1 FROM part_audio_objects AS pao
                   WHERE pao.video_part_id = vp.video_part_id)
  AND (
        latest.outcome = 'failed'
     OR (latest.outcome = 'no-subtitle'
         AND (  latest.error_code IN ('not_found', 'no-language-match')    -- definite
             OR (latest.error_code = 'inventory-empty'                     -- indefinite …
                 AND COALESCE(eic.confirmations, 0) >= 2)))                -- … corroborated
      );
```

`COUNT(DISTINCT run_id)` is load-bearing: two probes inside one run are one observation, so no retry
loop can inflate the count.

**A genuinely caption-less part still reaches the paid branch.** Its inventory is empty on every
probe, so every attempt records `inventory-empty`; two distinct runs give `confirmations = 2` and the
part is admitted — as before, one extra probe later. The `I-000187` part draws the same first code,
but its second probe reported `tracks=1`, so it never accumulates two empty observations, is never
selected, and `harvest-subs` stores `subtitle-ai`. Definite negatives stay immediate: `not_found` is
a claim about the part, not about the viewer's sight line.

Deliberate consequence: pre-existing `no-subtitle` rows carry `error_code IS NULL`, matching no
branch, so those parts stop admitting until re-probed and re-coded — conservative by design, since
treating an unknown legacy code as a confirmation is what let one unseen probe become a paid download.

## Read-only detection for pre-existing records

**The limit, plainly: the store persists no decoded-audio duration, so coverage for an
already-written part is not reconstructible from the archive alone.** Container `duration_s` is not
a substitute — it comes from a header, not from the decoded span the model consumed, and using it
would manufacture a number the run never measured. No sidecar held decoded duration for old runs.

So the read-only verdict has three values, computed from `coverage` alone:

| Archive state | Verdict |
|---|---|
| `coverage` present, `≥ 0.97` | **covered** — evaluable, clean |
| `coverage` present, `< 0.97` | **short** — evaluable; `stored-short` |
| `coverage` absent | **not evaluable** — not "covered", and not clean |

That third row is the answer. Read-only and from the archive alone, the operator **can**: name the
provably covered parts, name the provably short ones, and enumerate the remainder as *not
evaluable*. The operator **cannot**: say which unevaluable row is actually short, quantify the loss,
or date it. Detection is a *partition*, never a measurement — no read-only path may call a
pre-existing record fine. The audit reports the unevaluable count as a named number, so the unknown
is visible instead of absorbed into a success count. Stock is not rescanned: the fix reads stock and
reports honestly; a part becomes evaluable only by being re-run, which is where its evidence comes
from.

## Migration verdict

**No migration needed — and if any step below turns out to need one, stop and escalate rather than
writing it.** D10 adds no column: `subtitle_attempts.error_code` already exists, and D10 only adds
*values* to it plus a changed `v_missing_audio` body — code/schema rebuild, not data migration. D9's
quantities land in the record-shaped manifest entry, which grows by field, not by DDL. Existing rows
keep their shape and are handled by the conservative reading above. Consistent with the repo's
standing decision: schema rebuildable, no in-place migration.

## Spec 1 — asr-coverage-attestation (normative)

**Definitions.** For a part transcribed by one run: `decoded_s` = `sum(len(chunk) / SAMPLE_RATE)` over
every `(chunk, offset)` pair of the single `_split_audio` call that fed that run; `produced_s` =
`max(cue.end) − min(cue.start)` over that run's archived cues; `coverage = produced_s / decoded_s`;
`COVERAGE_MIN = 0.97`.

**Rules.**
1. Every run reaching the transcription loop MUST compute all three and write them to the part's
   manifest record: `decoded_s`, `produced_s`, `coverage`, `coverage_min` (constant used).
2. `coverage < 0.97` ⇒ `outcome = "stored-short"`, `error_code = "coverage-shortfall"`. The
   transcript is still written; the run does not abort and does not delete output.
3. `coverage >= 0.97` ⇒ `outcome = "stored"`, `error_code` None/unchanged — never `stored-short`.
4. `outcome = "stored"` with no `coverage` is invalid by construction; a run reaches a success
   outcome only by measuring itself.
5. `decoded_s = 0` ⇒ no coverage claim at all: outcome is the existing failure path, never `stored`.
6. A re-run recomputes all three from its own decode. It MUST NOT copy a prior run's evidence, and a
   re-run still short MUST leave `stored-short` standing.
7. Reading: present ∧ `>= 0.97` → **covered**; present ∧ `< 0.97` → **short**; **absent → not
   evaluable, never "covered"**. No reader infers coverage for a record without the field.
8. Empty transcript with non-zero `decoded_s` is `coverage = 0`, hence `stored-short` — not a
   no-speech or caption-less outcome.

**Witness** (both directions; write these without asking anything further):
- *Shortfall detected:* decode `d`, emit one cue spanning `[0, p]` with `p/d = 0.802` ⇒ assert
  `stored-short`, `error_code == "coverage-shortfall"`, transcript present. Basis: the measured
  `I-000188` part (73.561 s decoded / 0.0–59.0 s produced).
- *Full coverage NOT flagged:* cues spanning `p/d = 0.985` ⇒ assert `stored`, no `error_code`.
- *Boundary:* `p/d = 0.97` exactly ⇒ `stored` (the `<` is strict); `p/d = 0.80204` ⇒ `stored-short`.
- *Tiling:* `decoded_s` equals container duration on a known-length fixture; a disagreement means
  broken tiling, not a model drop.
- *Read-only:* a record with no `coverage` reports **not evaluable** and is never counted as covered.

## Spec 2 — caption-exhaustion-attestation (normative)

**Vocabulary.** A subtitle attempt (`kind='subtitle'`) records `outcome` plus a cause in `error_code`:

| `error_code` | Meaning | Weight |
|---|---|---|
| `not_found` | Gateway reported the part has no subtitle resource. | definite |
| `no-language-match` | Inventory visible; no track matched requested languages. | definite |
| `inventory-empty` | Inventory visibly empty — the credential may simply not see it. | indefinite |
| `NULL` | Legacy rows written before this change. | unknown |

**Rules.**
1. These causes MUST be recorded distinctly. One code must never mean both "the gateway said no"
   and "I saw nothing".
2. A definite negative admits a part to the paid branch on the first such attempt.
3. An indefinite negative admits only once `COUNT(DISTINCT run_id) >= 2` such attempts exist for that
   part (`CAPTION_EMPTY_CONFIRMATIONS = 2`). Two probes in one run are one observation.
4. `error_code = NULL` never confirms exhaustion; legacy rows are not grandfathered into admission —
   they are re-probed to be re-coded.
5. `v_missing_audio` keeps every existing guard (`processing_status <> 'gone'`, no transcript, no
   stored audio object) and adds the SQL in D10.
6. Preservation: a genuinely and repeatedly empty inventory still reaches the paid branch; the only
   change is that it takes two independent probes instead of one.
7. The human command (`probe-subs`) SHOULD report the cause it recorded, so "no subtitles visible"
   is never presented as the same finding as "gateway says none exist".

**Witness.**
- *Absent, seen once:* one attempt `error_code='inventory-empty'` ⇒ NOT selected. Basis: `I-000187`
  (one probe `tracks=0`; `harvest-subs` stored `subtitle-ai` minutes later; re-probe `tracks=1`).
- *Absent, confirmed:* two attempts with `inventory-empty` in two distinct runs ⇒ selected.
  Basis: the genuinely caption-less control part, `tracks=0` on all three probes.
- *Same-run repetition is not confirmation:* two `inventory-empty` attempts sharing one `run_id` ⇒
  NOT selected.
- *Definite negative is immediate:* one attempt `error_code='not_found'` ⇒ selected.
- *Unknown is not a confirmation:* one attempt with `error_code IS NULL` ⇒ NOT selected.
- *No false admission:* the `I-000187` part's second probe saw `tracks=1`, so it never accumulates
  two empty observations, is never selected, and `harvest-subs` stores `subtitle-ai`.

---

## Addendum — D11 (operator ruling, 2026-10-03) changes the carriers

**This addendum governs where it conflicts with D8/D9/D10 above.** The operator ruled **option 2**
(*evidence carried elsewhere*) after the writing-specialist seat found that the vocabulary D8/D9/D10
introduce is refused by two independent gates. Registered as `I-000200`; the costed options are in
`specs/blocker-schema-check.md`.

### What is now superseded

| Superseded in D8/D9/D10 | Replaced by |
|---|---|
| `outcome = 'stored-short'` | **No new outcome value.** `_ALLOWED_ATTEMPT_OUTCOMES` (`models.py:33`) is a four-value closed set and the `stored`-family CHECK forbids an `error_code`. |
| `error_code = 'coverage-shortfall'` | **No new error_code.** The coverage fact rides the **manifest row** — `decoded_s` / `produced_s` / `coverage` / `coverage_min` — which needs **no DDL**: `validate_manifest_record` ends in `return dict(entry)` (`manifest.py:105`) and does not reject unknown keys. |
| `error_code = 'inventory-empty'` | **No new error_code.** The admission distinction gets a **manifest-side observation count** (a non-`error_code` carrier, per D11). |
| `error_code = 'no-language-match'` | same — no new error_code value. |

### What survives unchanged

- The **measurement**, the **comparison rule** (`coverage = produced_s / decoded_s`), the **threshold
  derivation** (`COVERAGE_MIN = 0.97` from the measured `73.561 / 59.0 = 0.80204`), and the
  `_split_audio` tiling promise as the denominator's definition (D9).
- The **semantics** of D10 entirely: an indefinite negative (an empty inventory) admits only on
  `COUNT(DISTINCT run_id) >= 2` independent observations, while a definite negative admits at once;
  legacy `error_code IS NULL` rows are not grandfathered into admission. Only the *carrier* changes.
- The **witness sets** in both specs: they assert behaviour, not encoding, so they stand as written —
  read `outcome = "stored-short"` as *"the coverage evidence is present and below `COVERAGE_MIN`"*,
  and `error_code = "inventory-empty"` as *"an indefinite empty-inventory observation was recorded"*.
- **The no-migration verdict**, now genuinely: neither D9's fields nor D10's counter touch the
  `acquisition_attempts` CHECK, so the `CREATE TABLE IF NOT EXISTS` trap does not arise.

### Consequence for the plans

`caption-exhaustion-attestation` proceeds under D10 semantics + D11 carriers.
`asr-coverage-attestation` is **Blocked** by operator decision (`I-000201`: `I-000188` deferred), so
its D8/D9 carrier rewrite is deferred with it.
