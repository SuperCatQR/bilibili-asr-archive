# Harness issue acceptance on the published engine

2026-10-06: installed `@mstar-harness/engine` and `@mstar-harness/cli` 3.11.2 into ignored `.test-tmp/harness-runtime`, leaving the host installation and live registers unchanged. Bun 1.3.14 on Windows ran `scripts/verify_harness_concurrency.mjs` against the published engine package.

The engine package's snapshot writer requires an explicit `expectedVersion` content digest and checks it inside `withStatusWriteLock`. Root registration and unregister operations read the current root document inside that same root lock. The current upstream GitHub source differs from the published package's exact expected-version API; this evidence uses the installed distribution, not a guessed mapping to upstream HEAD.

Results:

- #192: register session B; retain the pre-A root read; concurrently register A and unregister B. The live root contains A after both finish. The tested public close mutation re-reads under its lock and cannot replay the retained stale root.
- #207: retain a snapshot and its version, then publish a peer fixture with the plan Done and no lease. A stale writer carrying the old version is refused with `coordination.version-conflict`; the complete Done snapshot is byte-equivalent after refusal. A stale InProgress row with a formerly held, structurally valid lease is also refused and cannot restore the released lease.
- #127: all 41 tracked workflow snapshots were reached by the engine validator. The original artifact-root/queue snapshots have terminal timestamps and validate. No document remains NOT-VALIDATED.

The reproduction uses newly allocated temporary harnesses and deletes only those fixtures. It does not hand-repair live engine documents. Run from the product root:

```powershell
npm.cmd install --prefix .test-tmp/harness-runtime @mstar-harness/cli@3.11.2 @mstar-harness/engine@3.11.2
bun scripts/verify_harness_concurrency.mjs .test-tmp/harness-runtime/node_modules/@mstar-harness/engine
```

The integrated real harness validation reports **44 documents, 43 OK, 1 FAIL, 0 NOT-VALIDATED**; tracked boundary passes with no volatile tracked files. The separate existing failure is workflow `20261004-issue-register-audit`: the published validator refuses `coordination.prepared.assignment_intent`. It does not concern terminal timestamps or stale writes, and it has not been bypassed or fixed by editing engine-owned state. CI marks the harness lane advisory, so a green CI badge alone would not establish that all documents validate.
