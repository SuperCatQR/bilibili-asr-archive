# PR #20 review — seed record

**Pinned by**: the driving session (session-03c3069a-68f3-4df6-ad4f-1ed145aec53d)
**Date**: 2026-09-27
**Tier**: deep (>300 changed lines) — 3 domain seats, no separate security seat
**Why 3 and not 2**: the three commits were authored together and two of them were written in
response to an earlier review *of the first one*; a seat pair that reviewed only the first would
reproduce the earlier review's blind spot rather than cover it.

Base: `1f2dcd0a62d1963f125b93107c3f3d0e1973e30f` (origin/main)
Head: `b43234bb9faba827e3f281650aa6f8c99d813ae0` (feat/20260927-aac-decode-contract)

| Seat | Domain | Pack | sha256 (first 16) |
|---|---|---|---|
| A | asr runtime code (decode/subprocess/errors/deps/resample) | `diffpack-core.txt` | `b0f0eb1d515e39dd` |
| B | tests and fixtures (mutation-testing every new test) | `diffpack-core.txt` | `b0f0eb1d515e39dd` |
| C | docs, pyproject, uv.lock, knowledge citations | `diffpack-core.txt` + `diffpack-uvlock.txt` | `f4430833bc375005` |

All three seats received the same core pack bytes and were told to build their own view rather than
trust any summary. Seats are read-only in the repository (writes only under /tmp); the driving
session decides what to change.

**Standing disclosure to every seat**: the first commit (`f4c0ebb`) was ALREADY reviewed by an
earlier adversarial read, whose findings became `d4f57cb`. The seats are asked to cover all three
commits — including re-checking that earlier review's conclusions rather than inheriting them.
