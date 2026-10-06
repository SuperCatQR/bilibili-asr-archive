# Publication I/O hardening: partial issues 49 and 50

Date: 2026-10-06. Source baseline: integration f280a2a. This change does not
fully resolve either issue and must not be used as a GitHub closing claim.

## Verified issue scope

`gh issue view 50 --json number,title,body,url` confirms the remote title itself
ends at `archive_bu`. Its body mentions four smaller items and `(c)` tuple
duplication, but gives no full `(c)` text or `(d)` description. No missing
acceptance detail is inferred. Visible `(a)` is already addressed by part-bound
repository reads on the current baseline; visible `(b)` is partially addressed
by the new verification deadline. Issue 49 concerns corpus-scale rehash cost.

## Safe implemented boundary

`services/bundle_verification.py` runs the existing strict completeness reader
in an exec child. It hashes all artifacts and detects same-size/same-mtime
content edits. No stat cache substitutes for content verification. The child
receives only a bounded declaration and no archive-writer descriptors
(`close_fds=True`), reads only, and returns a bounded completeness/error result.
Permission/device errors preserve their scalar errno class but never payloads.

`publish-transcripts --verify-timeout-seconds` defaults to 30 seconds, finite
and positive, for both pre-publication checks and post-publication confirmation.
Timeout preserves an unverified existing bundle, counts one failed candidate,
and permits later candidates. A healthy large/slow bundle may exceed the
budget and be refused; operators can increase the explicit budget. This is not
an integrity verdict that the bundle is corrupt. Process startup incurs extra
per-check cost; this favors bounded operational scopes over repeated full scans.

The parent kills a timed-out reader and waits at most 0.2 seconds for cleanup.
A kernel-blocked reader may outlive kill; the parent does not block on reap.
Four unreaped readers exhaust capacity and further checks fail closed. Those
workers cannot later publish because their only operation is verification.
Interruptions also trigger bounded cleanup. Process creation itself is outside
the bound, as are SQLite reads, artifact publication/fsync and manifest writes.

## Remaining gaps and whole-candidate fencing analysis

#49 remains a performance tradeoff: hashes are still necessary for strict
already-published decisions. Non-pending `--limit-parts N` bounds database part
selection and checks to N parts, and `--bvid BV:pN` gives an explicit narrow
scope. Pending limits count publication attempts, not previously-complete
bundles inspected; they can still scan the published corpus. Documentation
gives a roughly 10.5 GB / 3,000 bundle re-read example and scope guidance.
This mitigates operational cost, without eliminating unrestricted full hashes.

#50 remains partially open: a hung write, fsync, database or manifest mount
operation can still hold the parent writer lock. Moving these writes to a child
and releasing the parent's lock on timeout is unsafe: SIGKILL cannot guarantee
immediate cancellation of uninterruptible kernel I/O, and a blocked rename/write
could resume after another publisher acquires the lock. A user-space generation
fence checked before a syscall cannot revoke a syscall already in progress.
Giving the child the writer lock preserves safety but loses the requested
bounded lock-release promise. A reliable fence would require transactional or
remote storage semantics that can reject stale writes at the storage boundary;
none exists in the current mounted-filesystem design. No unsafe writer isolation
or unsupported claim of thread cancellation was introduced.

## Verification

Focused WSL verification used Ubuntu-24.04 and the existing pipeline venv:

```sh
cd /mnt/c/wt/bd-s/bilibili-asr-archive
PYTHONPATH=src /home/chosenecho/.venvs/bili-asr-pipeline/bin/python -m pytest -q tests/test_bundle_verification.py tests/test_cli_publish_transcripts.py tests/test_publish_read_failures.py tests/test_publish_pending.py tests/test_publish_candidate_limits.py tests/test_publish_bad_candidates.py tests/test_transcript_projection.py
```

Result before the last test-adapter timing fix: **96 passed, 1 failed in
118.98s**. The failing post-write fault injection patched the service after the
command had already bound its local verification function. Moving the adapter
installation before command entry repaired that test. Supplementary verification
of the full read-failure module, worker module, audio-only safety and the two new
CLI cases: **26 passed in 22.67s**. Together these runs cover every focused case.
Windows native `PYTHONPATH=src python -m pytest -q
tests/test_bundle_verification.py`: **8 passed, 1 skipped in 0.95s**; only the
POSIX descriptor-inspection case is skipped. This also exercises the hidden
Windows worker creation path. `git diff --check` passes. No live hung filesystem
experiment is claimed. Existing low-level injected reader-error tests now
explicitly substitute an in-process verification adapter so monkeypatched
`os.read` reaches the reader. This preserves their errno and no-overwrite
coverage. Separate real child tests cover process isolation, stall deadline,
continuation, descriptor noninheritance and strict content integrity; a fake
unreapable process tests bounded cleanup/capacity without manufacturing a real
unkillable kernel task.
