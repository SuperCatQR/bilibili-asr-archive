# Blocker found by the writing-specialist seat — D8/D9/D10 vocabulary is rejected by an existing CHECK

**Status: open. The PM lock must not clear this.** Verified by direct source read (not inference).

## The finding

The architect seat's decisions introduce vocabulary that two independent gates refuse to write:

| Decision | Introduces | Where it is refused |
|---|---|---|
| D8/D9 | `outcome = 'stored-short'` | `ALLOWED_ATTEMPT_OUTCOMES` (`storage/database.py:54` derives `_NO_TRANSCRIPT_ATTEMPT_OUTCOMES = ALLOWED_ATTEMPT_OUTCOMES - {"stored","unchanged"}`, then `_choice(outcome, ...)` validates against it) |
| D8/D9 | `error_code = 'coverage-shortfall'` | `CHECK (outcome IN ('stored','unchanged') AND error_code IS NULL ...)` — a `stored`-family attempt may carry **no** error_code |
| D10 | `error_code = 'inventory-empty'` | `CHECK (... OR (outcome = 'no-subtitle' AND (error_code IS NULL OR error_code = 'not_found') ...))` — only `NULL` or `'not_found'` is permitted |
| D10 | `error_code = 'no-language-match'` | same CHECK |

Verbatim, `storage/schema-transcripts.sql:88-91`:

```sql
    CHECK (
        (outcome = 'failed'
            AND error_code IS NOT NULL AND transcript_id IS NULL)
        OR (outcome = 'no-subtitle'
            AND (error_code IS NULL OR error_code = 'not_found')
            AND transcript_id IS NULL)
        OR (outcome IN ('stored', 'unchanged')
            AND error_code IS NULL AND transcript_id IS NOT NULL)
    ),
```

And the matching Python guard, `storage/database.py:1304-1307`:

```python
        if outcome == "failed" and error_code is None:
            raise ValueError("a failed attempt requires a bounded error_code")
        if outcome == "no-subtitle" and error_code not in (None, "not_found"):
            raise ValueError(
                "a no-subtitle attempt carries no error_code or not_found"
            )
```

So the refusal happens **twice** — in SQL and in Python — and a single-sided fix will not open the gate.

## Why the architect's "no migration needed" verdict is wrong as stated

D10's verdict reads: *"D10 adds no column — `error_code` already exists, only new **values** plus a replaced view body."* That is true of the **column**, and false of the **constraint**. Because the schema is created with `CREATE TABLE IF NOT EXISTS`, the CHECK on an **existing** database is never revisited: a rebuilt database would accept the new values, an existing one refuses them at `INSERT`. The architect's own rule — *"if any step below turns out to need one, stop and escalate rather than writing it"* — therefore fires on D8, D9 and D10 alike.

## What this blocks

- `asr-coverage-attestation` (D8/D9): cannot write `stored-short` or `coverage-shortfall` on an existing archive without widening the outcome/error_code contract first.
- `caption-exhaustion-attestation` (D10): cannot record `inventory-empty` or `no-language-match`, so the distinction the whole fix rests on cannot be persisted.

Both plans are implementation-blocked until this is decided. The witness sets the architect wrote are still valid as *specifications*; they are not yet writable.

## The decision required (escalated to PM, then operator)

Three shapes, each with a real cost:

| Option | Cost |
|---|---|
| **Widen the CHECK + vocabulary** (accept the new values) | Needs a schema-rebuild decision and a migration story for existing archives, which the repo's standing decision ("schema rebuildable, no in-place migration") was written to avoid |
| **Keep the CHECK; carry the evidence elsewhere** | The coverage evidence can still land in the manifest row (D9's placement) without a new `outcome`; the *admission* distinction for `I-000187` then needs a different carrier than `error_code` |
| **Re-purpose existing values only** | `outcome='failed'` already permits an error_code, and `no-subtitle` permits `'not_found'`; investigate whether the existing vocabulary can express both new facts without any new value — cheapest, but may lose precision |

## Provenance

- Found by the writing-specialist seat (Phase 1 chain seat 3), which correctly refused to edit a file whose base could not be trusted and escalated instead of papering over it.
- Independently re-verified by the PM by reading `schema-transcripts.sql:80-95` and `database.py:1296-1312` directly.
- Recorded before the compass lock deliberately: this is exactly the kind of thing that must not reach `status: locked` unexamined.

## Measured vocabulary (so the options are costed, not guessed)

`storage/models.py:33` — the attempt outcome vocabulary is a **four-value** frozenset:

```python
_ALLOWED_ATTEMPT_OUTCOMES = frozenset({"stored", "unchanged", "no-subtitle", "failed"})
```

`storage/models.py:49` — the error_code *shape* is permissive; only the CHECK set is narrow:

```python
_ERROR_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")   # up to 64 chars
```

So `coverage-shortfall`, `inventory-empty` and `no-language-match` are all **well-shaped** codes.
Nothing about their spelling is wrong; they are refused purely by the closed CHECK set and the
`no-subtitle` Python guard. That matters: the fix is a *contract* decision, not a naming problem.

## Re-costing option 3 (the cheapest shape) against the CHECK

The CHECK already admits two carriers the new facts could use without any new vocabulary:

| New fact | Could ride on | Constraint that must then hold |
|---|---|---|
| "coverage materially short" | `outcome='failed'` + `error_code='coverage-shortfall'` | CHECK requires `transcript_id IS NULL` for `failed` — so the transcript could **not** be referenced from the attempt. Whether the bundle still stands is a separate question the plan must answer. |
| "seen empty at least twice" | `outcome='failed'` + `error_code='inventory-empty'` | `failed` is **already** admitted by `v_missing_audio` (`latest.outcome IN ('no-subtitle','failed')`), which would make admission *immediate*, not corroborated — the opposite of D10's intent. |
| "visible but no language match" | `outcome='no-subtitle'` + `error_code=NULL` | Indistinguishable from legacy and from a genuine absence — loses exactly the distinction D10 exists to create. |

**Conclusion:** option 3 does **not** cover D10. `failed` being pre-admitted by the view means the
indefinite case cannot be expressed with the existing vocabulary at all. Option 2 (carry the fact
somewhere other than `error_code`, e.g. a coverage/admission column on the manifest row, which is
*already* D9's chosen home for coverage) remains viable for D8/D9 and needs a separate carrier for
D10's admission distinction. Option 1 (widen the vocabulary) is the only one that expresses
D10 as designed.

This is therefore a genuine product/architecture decision with no free option, which is why it is
escalated rather than resolved here.
