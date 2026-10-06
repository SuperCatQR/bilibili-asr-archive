# Re-lock record — iter-2026-10-register-burndown, after PR #214

> Written 2026-10-06 after the operator authorized "你把#214修好，然后合并" and it landed. This file **supersedes**
> the phase-2 dispatch assumptions of `direction-lock.md`; the original lock record stays on disk as the
> lock-time artifact it is. Baseline for every claim below: `main` = `a508d34` (control root merge of
> `dc1e78e`).

## 1. Why the original lock no longer holds

The original lock (2026-10-05) scoped 21 register rows into three plans and defined `≥20 resolved` as the
headline deliverable, with `D4` ruling that a row already fixed by someone else is recorded
*already-fixed* and **does not count**. On 2026-10-06 PR #214 merged and satisfies **20 of those 21 rows
in code**. Under the iteration's own rule the deliverable is therefore unreachable as written — not
"harder", *void*. Re-locking is the honest response.

## 2. Post-merge row re-verification (baseline `a508d34`, code read directly — not the PR's ledger)

| Row | GitHub | Verified evidence at `a508d34` | Verdict |
|---|---|---|---|
| `I-000182` | #184 | `finish_asr_run` called in `queue_source.py` | satisfied |
| `I-000183` | #185 | `selector_kind="bvid" if selector_target else "pending"` ×2 | satisfied |
| `I-000184` | #186 | `provenance_language` + `_last_language` plumbing (7 sites) | satisfied |
| `I-000197` | #199 | invocation-scope statements in the refusal docstring | satisfied |
| `I-000198` | #200 | `TypeError` inside the handled set | satisfied |
| `I-000199` | #201 | `src/bili_asr/diagnostics.py` `write_stderr` (descriptor-level) | satisfied |
| `I-000180` | #182 | `_common._now()` ×9, zero bare `int(time.time())` | satisfied |
| `I-000171` | #173 | `identity[1]` derivation, zero `page_index ... or 0` left | satisfied |
| `I-000176` | #178 | `test_pipeline_writeback_safety.py` + `test_cli_asr_writeback_refusal.py` | satisfied |
| `I-000194` | #196 | write-back after `status="archived"` (`cli/asr.py:287`) | satisfied |
| `I-000191` | #193 | stale phrase count **0** | satisfied |
| `I-000192` | #194 | `_record_transcript_writeback_failure` (7 sites) | satisfied |
| `I-000193` | #195 | `transcript_writeback_error` durable marker (3 sites) | satisfied |
| `I-000196` | #198 | `errors="replace"` count **0** (strict decode) | satisfied |
| `I-000202` | #204 | `_journal_bytes` count **0** (removed) | satisfied |
| `I-000203` | #205 | `_remove_journal` guarded (7 sites) | satisfied |
| `I-000168` | #170 | `opt_in_gate` performs `pytest.skip` itself | satisfied |
| `I-000174` | #176 | `test_installed_console_script_opens_and_initializes_database` | satisfied |
| `I-000175` | #177 | `test_cli_help` no longer in the baseline exclusion set | satisfied |
| `I-000210` | #210 | `credential_verified` required in both views (8 sites) | satisfied |
| **`I-000211`** | #211 | `_probe_part` still writes **no** durable trace | **OPEN — the only survivor** |

Behavioural confirmation (not just grep): on `a508d34`,
`tests/test_audio_pipeline_reliability.py`, `tests/test_pipeline_writeback_safety.py`,
`tests/test_cli_asr_writeback_refusal.py`, `tests/test_opt_in_gate.py`, `tests/test_cli_help.py`
→ **120 passed**. (`tests/test_installed_cli.py`'s 7 errors + 1 failure are **this host's** missing
`uv` + `ensurepip`; the same job is green in CI — verified in the `tests / python` log.)

## 3. The scale-budget problem, stated plainly

`scale = M` = **2–3 business plans**, and the only row this iteration's own rule lets it *count* is
`I-000211` (one row). Three plans cannot honestly be spent on one row, and inventing process plans to
fill the budget is explicitly forbidden. Two consequences:

- **This iteration cannot deliver "≥20 fixed by us" on the post-#214 baseline.** Saying otherwise would
  be exactly the falsification `D10` prohibits.
- **Re-scoping to the ≥20 target is still possible**, but it is a *new* direction — it must draw its
  batch from the 104 rows that remain, and it needs its own lock.

## 4. The 104 remaining open rows (measured `a508d34`)

Composition: `low/review-obligation` 52 · `medium/review-obligation` 24 · `low/improvement` 15 ·
`low/bug` 12 · `medium/bug` 8 · `medium/improvement` 7 · `high/review-obligation` 2 · `high/bug` 2 ·
`medium/decision` 1 · `low/risk` 1 · `high/risk` 1.

Excluded from any product batch by the original lock's reasons (all still valid, and still recorded in
`## Non-Goals`): `I-000215`, `I-000190`, `I-000207`, `I-000136`, `I-000135`, `I-000041`, `I-000209`.
Two of them are now **provably actionable outside a product plan** and new since the original lock:

- **`I-000209` (no CI)** — **factually resolved on 2026-10-06.** `.github/workflows/ci.yml` now exists,
  runs the suite, and is green (`tests / python`, `tests / harness`). The row is stale and should be
  closed with this evidence.
- **`I-000211`** — the one substantive survivor above.

## 5. Recommended re-lock (needs the operator's ruling)

**Route R1 — re-lock onto a new batch drawn from the 104 (recommended).**
Same user instruction ("评估项目issue，一批一批修复，至少修复20个"), new batch. Candidate clusters by
evidence size, none of which #214 touched:

| Cluster | Rows (open, post-#214) | Character |
|---|---|---|
| C1 — store-route expressiveness | `I-000126`, `I-000156`, `I-000066`, `I-000068`, `I-000104` | 5 medium; all "the store route cannot express X" |
| C2 — verification / evidence lane (residual) | `I-000211`, `I-000177`, `I-000172`, `I-000085`, `I-000079` | 5; tests that cannot currently witness what they claim |
| C3 — schema / status truth | `I-000042`, `I-000128`, `I-000044`, `I-000123` | 4; unreachable states, unreported degradation, duplicated config |
| C4 — review-obligation tail (L2 verdicts owed) | `I-000051`, `I-000095`, `I-000100`, `I-000078`, `I-000103`, `I-000122` | 6; owed verdicts, not code defects |

`C1 + C2 + C3` = **14 rows** in 3 plans (at the `M` cap). Adding `C4` would exceed `M`, so it is either
dropped or the scale moves to `L`.

**Route R2 — close this iteration as superseded.**
Record honestly: "the 21 declared rows were satisfied by PR #214 (20) + one still open; the iteration
produced no counted fix." Cheap, but it delivers nothing against the instruction and leaves the 104
untouched.

**Route R3 — keep as-is and pretend.** Not available. The row-level evidence in §2 forbids it.

## 6. One decision that is not mine

The 20 satisfied rows are **still open in the store and on GitHub** — PR #214's own ledger states
"GitHub issue states are unchanged", and it never ran `mstar issue close`. So the register still claims
125 open. Closing them requires the engine channel
(`{SPECS_DIR}/issue-store-close-route.md`: live lifecycle + engine-issued envelope), which is
**independent of which route is chosen in §5** and is the obvious first work item either way — it turns
20 rows of verified-fixed into 20 rows of *closed*, which is a real, countable deliverable that does not
need a new plan.
