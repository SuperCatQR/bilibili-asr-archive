# 2026-10-06 issue burndown integration

This batch uses actual GitHub issue numbers, independently reviewed source and
regression tests. The preceding PR 221 CI completed with **2757 passed, 61
skipped**. The current source adds bounded metadata observations, explicit
storage transaction ownership, artifact-root attribution, final-file symlink
refusal, consistent usable-audio resolution, store-qualified recovery and exact
quality artifact identity. Documentation and independent historical reviews
resolve separately identified contract and review debts.

## Current integration checks

- Native Windows storage, metadata, quality and added contract tests:
  **253 passed in 126.88 seconds**.
- Native Windows runtime/publication tests: **23 passed, 4 skipped**. The skips
  require link creation capabilities unavailable on this runner. Three old
  inventory assertions were corrected to compare POSIX-normalized paths.
- WSL current quality suite after the identity fix: **72 passed**.
- WSL current publication and added artifact/audio-only contracts after the
  Windows assertion update: **18 passed**.
- Lane verification: storage **180 passed**, supplementary metadata **38
  passed**; runtime **227 passed**; documentation **140 passed**; independent
  historical review's current seven suites **155 passed**. These overlap;
  they must not be summed as a unique test count.
- Released harness engine 3.11.2: real concurrent registration/closure and stale
  snapshot mutation reproductions passed. Real harness validation reached all
  documents: **43 passed, 1 failed, 0 not validated**. The remaining existing
  `assignment_intent` schema incompatibility is disclosed in the engine report;
  an advisory CI badge does not prove this check passed.

The full WSL baseline completed: **2783 passed, 61 skipped in 1045.57 seconds**.
It started before the final quality identity and assertion updates; those changed
modules were rerun afterwards as recorded above. Final GitHub CI validates the
uploaded integrated tree. No live Bilibili enumeration, new GPU
model run or external archive coverage measurement is claimed by these tests.

## Acceptance evidence

- [Exact-number audit](issues-current-acceptance-audit.md): existing source and
  tests for historically unclosed fixes, distinguishing inspection from execution.
- [Storage](issues-storage-burndown.md): #69, #70, #75, #90, #92, #93.
- [Runtime](issues-runtime-burndown.md): #48, #104, #125, #126, #158.
- [Documentation](issues-docs-burndown.md): #83, #164, #165, #171, #177 and
  qualified historical wording for #41/#61.
- [Independent historical review](../../verification-results/independent-historical-review.md):
  #66/#103, including findings and the current identity fix; #101's preserved
  aggregate missing-artifact contract.
- [Engine concurrency](issues-engine-concurrency.md): #127/#192/#207.

#49's strict content-verification cost and #50's complete candidate filesystem
deadline remain open engineering work. Read-only process isolation can bound
verification latency; it cannot safely promise cancellation of a kernel-blocked
publication write. No unsafe release of a writer lock is accepted as a fix.
