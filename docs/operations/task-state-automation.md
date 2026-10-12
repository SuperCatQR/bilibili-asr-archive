# Automatic task state evidence

The task-state backup policy saves the whole database, transcript/editorial/run
evidence, declared typed controls, and the backup job's own policy, running
receipt, prior results and scheduler state. It uses stored ZIP members. Audio
is a verified external identity dependency, so state evidence is not a media
self-contained archive and is never advertised as immediately runnable.

Create a separate repository and explicitly enable a policy:

```sh
bili-asr maintenance backup-policy \
  --source-root /srv/archive --repository /srv/state-backups \
  --profile task-state --mode full --compression stored \
  --interval-seconds 3600 --keep-count 5 --keep-days 30 \
  --external-components /srv/control-declarations.json \
  --output /srv/task-state-policy.json
python scripts/deployment/run_archive_backup.py \
  --policy /srv/task-state-policy.json --poll-seconds 60
```

The declaration file contains an object with a `components` list. Every entry
names a supported kind, canonical absolute source path and the controller's
actual stable lock path:

```json
{"components":[{"kind":"retry-control/v1","path":"/srv/ops/retry-control.json","lock_path":"/srv/ops/retry-control.lock"}]}
```

An archive without external retry controls must explicitly use
`--no-external-control-state` instead. Unknown/untyped external control formats
are refused; converting a controller's state is a separate explicit adapter
operation. Never declare unrelated locks to bypass the controller's writes.
The task-state evidence documentation describes supported component versions.

The controller locks are acquired before the shared archive access and SQLite
read transaction. This lets a long-running, idle WRITE session coexist with
state capture. Full media snapshots still require their exclusive maintenance
lock. A SQLite backup captures committed database state; external controls and
immutable evidence have recorded observed byte versions. The manifest states
that this is not one atomic transaction across all components. A change during
capture fails rather than silently mixing evidence.

Time, manual and durable event triggers use the same policy and receipts:

```sh
bili-asr maintenance backup-run --policy /srv/task-state-policy.json --trigger manual
bili-asr maintenance backup-run --policy /srv/task-state-policy.json \
  --trigger event --event-id job-attempt-completed-123
bili-asr maintenance backup-status --repository /srv/state-backups --policy-id POLICY_SHA256
```

Repeated completed invocations verify their package before reuse. Completed
event receipts prevent a duplicate event run across scheduler restarts. A
published package interrupted before the final receipt can be adopted only
when its policy and current invocation match. Failed captures retain a reason,
increment consecutive failures and emit a durable failure/threshold alert;
they do not move the last successful restore point. Notifications are local
machine-readable events for an operator or supervisor to consume.

Automatic retention selects only verified packages with successful receipts
owned by this exact policy. It retains the newest configured count and points
inside the day window, always including at least the latest successful point.
It leaves other policies' packages, all run receipts, source database records
and audio untouched. State packages are independent full evidence points, so
they do not need the media snapshot dependency chain.

Use the `task-state` read-only CLI to inspect a package without importing it
into an active archive. Database job/attempt/lease values remain original
historical evidence. A `running` status or stored process identifier never
revives a worker. This policy does not reset physical call budgets, release
holds, requeue jobs or implicitly transfer/delete inactive hot-library records.
Explicit inactive transfer requires a separate policy and verified receipt;
retaining complete queryable backups does not authorize hot-library cleanup.
