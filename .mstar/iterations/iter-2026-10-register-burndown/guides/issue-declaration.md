# Issue declaration — the 21 rows scoped into `iter-2026-10-register-burndown`

Declared 2026-10-05 at the operator's request ("声明你处理的 issues，在 github 中标记出"). This file is the
authoritative store-id ↔ GitHub-issue map for the iteration, so the closure step (`mstar issue close`) and the
PR body can both point at the same numbers without re-deriving them.

## What was done on GitHub

- Created label **`iteration:iter-2026-10-register-burndown`** (`#0e8a16`,
  description *"Scoped into iteration iter-2026-10-register-burndown (fix batch B1/B2/B3)"*).
- Added that label to all **21** open issues listed below (verified: `gh issue list --label
  iteration:iter-2026-10-register-burndown` returns exactly 21).
- Added one comment per issue naming its batch and its plan file, and stating that acceptance is unchanged
  and the closure will name the fixing commit.

These GitHub issues are a **mirror** of `{HARNESS_DIR}/store.db` with independent numbering — GitHub numbers
are *not* store ids. The store id is what `mstar issue close` consumes; the GitHub number is what a reviewer
sees. Both are recorded per row.

## B1 — `{PLAN_DIR}/asr-run-record-integrity.md` (10 rows)

| store id | GitHub | severity / kind | GitHub title (head) |
|---|---|---|---|
| `I-000182` | #184 | medium / bug | a `kind=asr` acquisition run is never finished |
| `I-000183` | #185 | low / bug | bvid-scoped asr records `selector_kind=pending` |
| `I-000184` | #186 | low / bug | default asr path stores `language='und'` |
| `I-000197` | #199 | low / improvement | run-refusal diagnostic latch scope unstated |
| `I-000198` | #200 | low / bug | narrowing `ensure_asr_run`'s except drops `TypeError` |
| `I-000199` | #201 | low / bug | D8 diagnostic changes exit code to 120 |
| `I-000180` | #182 | low / improvement | `_common.py`'s injectable clock bypassed in `queue_source.py` |
| `I-000171` | #173 | medium / bug | write-back `page_index` defaults to 0 |
| `I-000176` | #178 | medium / review-obligation | R14 store write-back has no end-to-end witness |
| `I-000194` | #196 | medium / bug | ASR write-back runs before the row is marked archived |

## B2 — `{PLAN_DIR}/archive-writeback-durability.md` (6 rows)

| store id | GitHub | severity / kind | GitHub title (head) |
|---|---|---|---|
| `I-000191` | #193 | low / bug | two coordinator docstrings assert a superseded order |
| `I-000192` | #194 | low / improvement | caption write-back has no swallow boundary |
| `I-000193` | #195 | medium / bug | terminal caption row can never acquire its transcripts row |
| `I-000196` | #198 | low / bug | manifest journal decode policy is asymmetric |
| `I-000202` | #204 | low / improvement | `_journal_bytes` is write-only state |
| `I-000203` | #205 | low / risk | `save()` publishes before discarding the journal |

## B3 — `{PLAN_DIR}/verification-lane-contract.md` (5 rows)

| store id | GitHub | severity / kind | GitHub title (head) |
|---|---|---|---|
| `I-000168` | #170 | medium / bug | `opt_in_gate` returns but never skips |
| `I-000174` | #176 | medium / review-obligation | installed lane never opens a database |
| `I-000175` | #177 | medium / improvement | `verify_baseline` excludes `test_cli_help.py` wholesale |
| `I-000210` | #210 | medium / bug | credential-absent runs satisfy the corroboration rule |
| `I-000211` | #211 | low / bug | `probe-subs` leaves no durable trace |

## Not declared (deliberately out of scope)

Recorded so the absence is a decision rather than an omission. Each reason lives in compass
`## Non-Goals`:

| Row | Why not |
|---|---|
| `I-000215` (gh #? — captured in the store only) | engine/lifecycle wedge, operator-ruled owner blocker |
| `I-000190`, `I-000207`, `I-000195` | engine shared-register lost-update family — not product code |
| `I-000136`, `I-000135` | `uv.lock`/dependency closure; regeneration pulls a PyPI CUDA torch |
| `I-000041` | store `acceptance` field reads `defer` — a recorded operator deferral |
| `I-000189` | proofread-merge block accounting; coherent but shares no module with B1–B3 |
| `I-000209` | standing up CI is a repo/host operation |

## Closure contract reminder

The GitHub issue is the **mirror**; the authority is the store row. When a row is fixed, the closure goes
through `mstar issue close` against a live lifecycle with an engine-issued envelope
(`{SPECS_DIR}/issue-store-close-route.md`), citing the fixing commit and the red→green witness. Closing the
GitHub issue without the store closure (or vice versa) leaves the two in disagreement — both are done
together, and the PR body carries the 21 numbers so the reviewer can check the pair.
