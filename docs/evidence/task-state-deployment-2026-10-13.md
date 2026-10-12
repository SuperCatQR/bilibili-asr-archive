# Task state backup deployment acceptance

The separately authorized acceptance container at `i-1.gpushare.com:41631`
ran the actual backup scheduler under Supervisor on 2026-10-13 Asia/Hong_Kong.
This is a separate frozen fixture archive; the old production controller and
its database were not migrated or modified.

Two real Supervisor processes ran concurrently: `bili-asr-state-idle-writer`
held `ArchiveSession(... WRITE).open()` for its whole lifetime, and
`bili-asr-task-state-backup` invoked the production scheduler every two seconds
against a policy due every ten seconds. The source included a running job with
an original lease observation, committed WAL state, and declared typed external
retry holds and a spent ledger entry protected by the controller's stable lock.

Before stopping this bounded probe, the scheduler had **27 successful scheduled
runs** while the idle writer stayed RUNNING for 4 minutes 52 seconds. The
explicit policy retained **two verified independent state points**. All run
receipts remain auditable. Audio payload count was **zero**; the package carried
one verified media identity dependency. Original control bytes remained exact.
The source's committed table ledger matched the captured package ledger, and
all non-job tables matched the original preflight. The first preflight used an
immutable SQLite reader and therefore missed the fixture's job update in WAL;
the acceptance check corrected this by taking a SQLite backup of the live
read-only source and fingerprinting that committed snapshot, instead of
claiming the earlier immutable result was current.

The actual offline reader selected the running job by job ID, part, stage and
status, returned its original payload JSON and lease owner, and also queried
the workflow_jobs raw-table adapter. No active library import, provider call,
model installation, media restoration or worker dispatch was performed by the
reader. The archived status remains inactive historical evidence.

Both probe programs were explicitly stopped after capture. The independently
deployed retry-maintenance service remains a separate process. Private evidence
is retained under `/root/issue-acceptance/evidence/state-supervisor-{preflight,acceptance}.json`
and the scheduler logs; it records source file identities and the exact policy.
The final source redeployment and fresh remote regressions are recorded with
the PR's CI results. No claim is made about production-scale timings or
unbounded historical receipt growth.

The consistency protocol records a SQLite read transaction, controller locks
and stable observed component byte versions. It explicitly declares
`atomic_cross_components:false`, `media_self_contained:false`, and an inactive
read-only restore policy. Full media snapshots keep their exclusive lock.
