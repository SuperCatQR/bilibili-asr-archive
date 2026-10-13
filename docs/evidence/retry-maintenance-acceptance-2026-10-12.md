# Retry maintenance deployment acceptance

The user-provided server was a new container with `docker-init` as PID 1 and
an existing Supervisor. It contained no original archive or external production
retry owner. Acceptance used a private synthetic archive and exact job IDs,
without provider credentials or paid calls. This is a deployment of the
repository's independent maintenance process in the requested environment.
It is not evidence of migrating the original production database or stopping
its external `production_ops.py` owner.

## Scheduled lifecycle and persistence

The installed Python 3.12 environment ran the repository CLI. The existing
Supervisor loaded `/etc/supervisor/conf.d/bili-asr-retry-maintenance.conf` and
started the scheduler with a two-second interval, a 120-second pass timeout,
process-group shutdown and private file permissions. Two consecutive scheduled
success timestamps were `1791819446` and `1791819449`. After an explicit
Supervisor stop, health reported `stale` while the separate worker snapshot
still reported `alive`. Restart recorded success at `1791819453`, kept the
ledger and holds unchanged, and returned `healthy`. The resulting status was
RUNNING at **2026-10-12 23:37:35 Asia/Hong_Kong**.

Of five explicitly selected fixture jobs, only the transient failure was
requeued, consuming one durable retry. The held job, exhausted job and source
quality failure remained failed; the cancelled job remained cancelled. All
five attempts were retained. Preflight left state untouched and reported the
same scope decisions; it correctly retained `handoff_verified=false`.

Private authoritative evidence remains on the server under
`/root/issue-acceptance/evidence/`: `retry-supervisor-acceptance.json`,
`retry-supervisor-preflight.json`, `retry-supervisor-failure-recovery.json`,
`retry-supervisor-final.json` and `retry-tests.log`. The fixture archive and control files are under
`/root/issue-acceptance/retry-deployment-v3/`. The scheduler configuration
selects only those acceptance jobs.

With the real Supervisor process running, temporarily removing the required
holds object produced `health_status=failed`, `error_code=ValueError`; holding
the maintenance lock across two passes preserved the last success timestamp,
incremented `lock_skip_count` to two and produced `health_status=stale`.
Restoring state and releasing the lock produced a new `healthy` success at
**2026-10-12 23:41:40 Asia/Hong_Kong**, without changing any ledger entry.
After acceptance, the policy interval was changed to the ordinary 60 seconds
under the same maintenance lock. The still-running scheduler consumed that
policy and reported healthy at **2026-10-12 23:45:31 Asia/Hong_Kong**.

## Worker and failure admission

The server ran 56 tests from `test_retry_maintenance_runtime.py`,
`test_retry_maintenance_scheduler.py`, `test_retry_maintenance.py`,
`test_retry_preflight.py` and `test_retry_maintenance_policy_integration.py`:
**56 passed in 27.58 seconds**. These exercise real subprocess scheduling,
installed CLI dispatch, SQLite workflow storage and editorial handlers with
an offline provider double.

The two-chunk legacy input test saved the first successful checkpoint and the
second chunk's original rejected response, committed no complete revision and
left render unattempted. Maintenance did not widen admission to
`RevisionValidationError`. A separate two-chunk transport-failure test ran the
actual scheduler, durably reserved a retry, reopened the worker repository,
called only the unfinished chunk, committed the complete revision and rendered
through ordinary dependency admission. A cancelled historical render stayed
cancelled. Prior calls and the successful first checkpoint were unchanged.

Real subprocess tests distinguish a missing-state preflight failure, repeated
maintenance-lock skips and stopped maintenance from worker liveness. They
also verify timeout termination, failed-pass continuation, SIGTERM shutdown,
backoff, exhausted budgets, manual holds, source-quality denials and uncertain
reservations retained across restart. An isolated mutation changing a failed
pass into a completed pass was rejected by the scheduler regression test.

The shared automatic failure policy and physical provider budget gates remain
unchanged. Historical reference failures still require the existing reviewed
manual retry or repair process; deployment does not silently enable them.
