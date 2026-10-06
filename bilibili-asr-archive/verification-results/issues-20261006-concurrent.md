# Concurrent issue repair — 2026-10-06

Integration branch: `iteration/iter-2026-10-issue-concurrency`, based on `main`
at `fc44443`. Plan: `.mstar/plans/20261006-concurrent-issue-fixes.md` (workspace-relative).
Three agents implemented isolated feature lanes in separate worktrees, followed
by parent review, integration and cross-platform regression verification.

## Delivered scope

| Current GitHub issue | Local result |
| --- | --- |
| #216 | Immutable CLI metadata owns handlers, explicit mutation/lock and artifact policies, and retention flags. Parser completeness is checked; omission or invalid policy types fail. Existing canonical-state writer classifications and package monkeypatch seams are preserved. |
| #217 | Root README explains product/workspace/harness boundaries, installation and actual CI checks, local data and operational links. No standalone linter is invented. |
| #218 | Harness retention policy distinguishes durable records from raw evidence; defines measured review triggers, immutable external pointers, member/archive hashes, independent copies and restore verification. No evidence was removed or uploaded. |
| #211 | Recorded decision preserves read-only probe inspection; durable observations belong to harvest, and probes never authorize exhaustion or paid audio acquisition. |
| #219 | Removed leftover clock-extraction spacing and corrected `ensure_asr_run` wording to per-source scope, with separate invocation diagnostic scope. Single persisted-time helper and removed redundant search guard were already implemented. The reachable `escaped_raw` guard remains necessary. |
| #220 | Live `git ls-remote --heads origin iteration/iter-2026-10-ledger-integrity` returned no ref. Removed only stale local remote-tracking ref with expected tip `ec9d3d2`; no related local branch/worktree remains. Existing retirement guide records squash evidence and recovery via PR #35. |
| #210 | Already implemented before this batch: both SQL confirmation CTEs require present and verified credentials; anonymous observations do not corroborate. Verified existing regressions rather than crediting a new fix. |

Follow-up `bce6b4d` preserves named unknown-command errors through the parser
monkeypatch seam and adds a real non-POSIX directory-openability probe. Denied
Windows artifact roots now refuse before dispatch; the test injects the actual
platform primitive. Directory-symlink tests skip only when creation is unavailable.

## Current-issue mapping audit

The older `issue-fix-batches.md` uses inconsistent GitHub numbers in some early
tables. For example current #184 is ASR run finalization, #185 selector scope,
and #186 language attribution. Use current issue titles and actual tests rather
than those old table numbers when reconciling state.

| Already implemented current issues | Existing regression evidence (product-relative tests) |
| --- | --- |
| #184, #185, #186 | `test_audio_pipeline_reliability.py`: run scope/language/completion, interruption and coordinator/pilot finalization regressions. |
| #187 | `test_archive_producer_health.py`: real standalone ASR requires no campaign sidecars; coordinator and unknown-producer controls retain evidence requirements. |
| #189, #210 | `test_storage_queue_gaps.py`: one empty inventory, anonymous/mixed credentials, unverified cookies and newest unverified observations. |
| #190 | `test_asr_coverage_attestation.py`: recorded 59.0/73.561-second partial span and publication attestation; measured temporal coverage does not prove speech completeness. |
| #191 | `test_proofread.py`: missing side-by-side row refuses merge. |
| #193, #194, #195, #196 | `test_coordinator.py`, `test_pipeline_writeback_safety.py`, `test_audio_pipeline_reliability.py`, `test_cli_asr_writeback_refusal.py`: published bundles survive refused supplementary writes; durable errors and retry selection persist. |
| #198 | `test_pipeline_recovery_quality.py`: corrupt UTF-8 cannot become rewritten identity. |
| #199, #200, #201 | `test_pipeline_writeback_safety.py`: connection-contract refusal across batches and actual closed-stderr subprocess exit codes. |

#192 and #207 concern engine-owned concurrent register/snapshot writes; product
changes do not repair them. #127 concerns terminal engine snapshot validity.
The installed harness engine is unavailable in this environment. No engine
register was hand-edited, and no GitHub issue was closed or commented on.

## Verification

Initial primary WSL targeted baseline: **147 passed, 53 skipped**. Native
Windows credential/probe subset: **15 passed**. CLI lane focused WSL regression:
**325 passed, 1 skipped**; final explicit-policy registry subset: **91 passed**.

Initial Windows registry/help/artifact-root lane: **213 passed, 2 failed**.
Failures exposed missing symlink privilege handling in a test and the Windows
configured-root openability check gap. After the follow-up, the integrated
Windows registry/help/artifact-root suite passed **228 tests, 4 skipped** in
17.06 seconds; all four skips concern unavailable symlink privileges.
Final integrated WSL registry/help/artifact-root/writeback-safety checks passed
**248 tests** in 48.58 seconds. Source, test and script compilation and
`git diff --check` pass.

Integrated harness boundary: **OK**, `tracked=529`, `volatile-tracked=0`.
The checker exits **1** because 43 engine documents are **NOT-VALIDATED** without
`mstar`; this is not an authoritative lifecycle validation pass. WSL tests in
Windows-created worktrees cannot use Linux Git with their Windows absolute
gitdir links; final integration tests use the primary checkout's real `.git`.

Full WSL suite (`python -m pytest -q -ra`) passed **2,756 tests, 61 skipped,
zero failures**, in **943.31 seconds**. It began after integration at `ee186fb`;
the later behavior-neutral #219 cleanup and `bce6b4d` compatibility/platform
follow-up were covered by the final integrated 248-case WSL and 228-case Windows
checks above, rather than repeating the full provisioning suite. The full run
has 2,817 accounted-for cases; the follow-up adds one parser-seam regression.
The 61 skips are 53 unavailable harness-engine checks, four opt-in live checks,
three opt-in scale checks and one unavailable real-ASR-model chain check.
Runtime logs/JUnit remain local under `.test-tmp/`; this report retains the
reviewable outcome. Live upstream, opt-in scale and real GPU/model behavior are
not established by the offline suite.

## Delivery state

All lanes are merged locally into the iteration branch. Feature worktrees
`codex/issue-216`, `codex/issue-217` and `codex/issue-218` remain available for
review. Existing unrelated worktrees/runtime files were preserved. `main` and
GitHub issue states were not changed; no branch was pushed and no PR published.
