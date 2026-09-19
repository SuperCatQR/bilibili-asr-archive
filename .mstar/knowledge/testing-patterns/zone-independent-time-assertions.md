---
module: bili-asr verification
date: 2026-09-19
last_updated: 2026-09-19
problem_type: testing_pattern
category: testing-patterns
severity: medium
plan_id: 20260919-sqlite-queue-bridge
applies_when:
  - asserting a rendered date, time or locale-dependent value
  - an expectation computed with the same helper the implementation calls
  - a test that passes locally and cannot fail on the CI runner's zone
tags:
  - timezone
  - determinism
  - monkeypatch
  - test-expectations
  - struct-time
---

# Zone-independent assertions on rendered time values

## Context

A derived manifest row carries `pubdate_str`, rendered by the module as
`time.strftime("%Y-%m-%d", time.gmtime(pubdate))` — the second's **UTC** calendar date
(`bilibili-asr-archive/src/bili_asr/services/manifest_derivation.py:95`). The first test anchor asserted
the literal date, which discriminates only on a host whose own local date for that second differs from
its UTC date: the development host is `+08:00` and caught it, the CI runner is UTC and cannot. An
assertion whose ability to fail depends on where it runs is not an assertion.

Three plausible repairs were tried or considered, and **two of them do not work**:

| Repair | Why it fails |
|---|---|
| Render the expectation with `time.gmtime` | Still no discrimination on a UTC runner: `gmtime` ignores `TZ`, so the expectation and the value under a `localtime` regression are the same string there. |
| Assert a second epoch whose UTC and local dates differ | Measured **non-discriminating**: on a UTC runner the local date of *any* epoch is its UTC date. With `time.gmtime(pubdate)` swapped to `time.localtime(pubdate)` in `row_for_part`, the suite still passed **18/18** under `TZ=UTC`. |
| Pin `TZ` inside the case (+ `time.tzset()`) | `tzset` is not portable, and it leaves the assertion's discrimination to the environment it pins. |

## Guidance

**Rule: supply the host-dependent inputs yourself, and assert a literal the host cannot influence.**

1. **Stub both clocks the module composes** — `time.gmtime` *and* `time.localtime` — with fixed
   `struct_time` values a day apart (`1970-01-01T23:59:59` vs `1970-01-02T07:59:59`), and assert the literal
   day (`"1970-01-01"`). No host zone can make the two stubs equal, so a `localtime` rendering fails
   everywhere and the UTC rendering passes everywhere; the runner's zone stops participating:

   ```python
   monkeypatch.setattr(manifest_derivation.time, "gmtime", lambda _epoch: utc_day)
   monkeypatch.setattr(manifest_derivation.time, "localtime", lambda _epoch: local_day)
   assert row_for_part(part, PUBDATE_UTC_DAY_EDGE)["pubdate_str"] == "1970-01-01"
   ```

2. **Never render the expectation with the function under test.** An expectation computed from `gmtime`
   confirms whichever stub the code chose; the asserted value has to come from outside the implementation
   (a literal here, or a value derived by a different route).
3. **Prove the case fails when the regression is present.** Inject the swap
   (`time.gmtime(pubdate)` → `time.localtime(pubdate)`), run under every zone the project cares about
   (`TZ=UTC`, the host's `+08:00`, `America/Los_Angeles`) and record the counts — the shipped construction
   failed **2/20 in all three zones** with the swap and passed **20/20** clean. A discrimination claim
   without that measurement is the same kind of over-claim as a comment wider than its code.
4. **Put the discrimination in its own case, one per anchor.** Two anchors were in play (the pure mapping,
   and the CLI writing the mapping's value through the manifest store), so two cases were added rather than
   rewriting a shared fixture that five other cases use.
5. **State the stub's scope limit.** The stubs intercept exactly the two functions named; a future switch to
   another local-time API (`datetime.fromtimestamp`) would leave the case silent and fall back to the
   host-conditional anchor. Keep that anchor as a second net (it still discriminates on any non-UTC host)
   and record the limit next to the case.

## Why This Matters

A host-conditional assertion is worse than a missing one: it is green in CI, so a regression in the
rendering ships, and the case's name claims a check nobody gets. Deriving the expectation from the same
helper the implementation calls is the same defect in a quieter form — on a host where both agree, the test
is a tautology that reads as verification. Stubbing the host's variable inputs is what converts "passes on
my machine" into an assertion with a fixed meaning, and it needs no `tzset`, no environment dependency and
no second epoch.

## When to Apply

- Asserting any rendered date, time, timestamp, duration or locale-formatted value.
- Any expectation computed with the same function the implementation calls (a test that recomputes the
  implementation's expression is not an independent expectation).
- A case that passes on the development host and would pass on a UTC CI runner for the wrong reason.
- Not needed when the value under test is already host-independent (a stored epoch, a stored string): assert
  it directly and skip the clock plumbing.

## Examples

### Before — the literal only discriminated off-UTC

```python
# pubdate_str is the UTC day of a fixed publication second; the old test asserted
# the literal, which fails under a localtime regression only where the host's own
# date differs from the UTC date.
assert row["pubdate_str"] == PUBDATE_STR      # PUBDATE_STR = strftime("%Y-%m-%d", gmtime(PUBDATE))
```

### After — both clocks supplied, one literal asserted

```python
def test_the_rendered_day_is_utc_regardless_of_the_runners_zone(monkeypatch):
    utc_day = time.struct_time((1970, 1, 1, 23, 59, 59, 3, 1, 0))
    local_day = time.struct_time((1970, 1, 2, 7, 59, 59, 4, 2, 0))
    monkeypatch.setattr(manifest_derivation.time, "gmtime", lambda _epoch: utc_day)
    monkeypatch.setattr(manifest_derivation.time, "localtime", lambda _epoch: local_day)

    row = row_for_part(_part(), PUBDATE_UTC_DAY_EDGE)   # 86_399 = 1970-01-01T23:59:59Z

    assert row["pubdate_str"] == "1970-01-01"
```

## Evidence

- Iteration: `iter-2026-09-queue-bridge`; plan `20260919-sqlite-queue-bridge`.
- Cases: `bilibili-asr-archive/tests/test_manifest_derivation.py:120-144` (the mapping) and
  `bilibili-asr-archive/tests/test_cli_derive_manifest.py:295-331` (the CLI end to end, seeded with
  `pubdate=86_399`).
- Implementation under test: `bilibili-asr-archive/src/bili_asr/services/manifest_derivation.py:95`.
- Measurements (recorded in the plan's `## Review Gate Summary` and
  `{SDD_DIR}/20260919-sqlite-queue-bridge/review/qc1.md`): the second-epoch variant passed **18/18** under
  `TZ=UTC` with the `localtime` swap injected (non-discriminating); the shipped `struct_time` construction
  fails **2/20** with the swap in each of `TZ=UTC`, `+08:00` and `America/Los_Angeles`, and passes
  **20/20** clean.
- Scope limit carried: the stubs cover `time.gmtime` / `time.localtime` only; a move to another local-time
  API would leave the case silent.
