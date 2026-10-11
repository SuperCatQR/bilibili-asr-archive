# Artifact online validation — 2026-10-11

The fixed storage implementation is `8d6ab213e9a1fea380d8c1b0ec95f6d643da2ab8`.
This revision includes the independent regression tests and fix for a target
package changing after its member SHA verification. The final release captures
the package generation before reading, compares it after reading, and compares
the same original generation immediately before deletion.

The results below use generated fixture bytes and isolated archives. They do not
touch production archives, run media downloads, or run real ASR/AI. Automatic
policies remain off unless explicitly configured. The source checkout needs the
development dependencies, including `pytest` and `jsonschema`.

## Reproduce the bounded multi-process soak

Run on Linux/WSL from the repository root:

```sh
PYTHONPATH=src:. python scripts/validate_artifact_online.py > artifact-online-validation.json
```

For a Windows-managed Git worktree opened through WSL, Linux Git may not resolve
the Windows `.git` pointer. Obtain the revision using Windows Git first, then
pass it explicitly:

```sh
PYTHONPATH=src:. python scripts/validate_artifact_online.py \
  --source-revision 8d6ab213e9a1fea380d8c1b0ec95f6d643da2ab8 \
  > artifact-online-validation.json
```

The script creates and removes its own temporary fixture directory. It accepts
no archive root or storage target argument. Two readers repeatedly pin, restore
when required, and verify the full SHA-256 of a 4 MiB object. Two migrators each
complete six offload/restore cycles against the same object. The parent checks
every child result and exact preservation of all business tables. Unexpected
errors fail the run; the only retried transfer errors are identified stale-plan
or retention races. The script separately measures the public policy executor
with a 16 MiB object and a real 32 MiB/s I/O limit.

Each reader performs 160 bounded attempts. The migration deadline is 75 seconds;
the parent deadline is 90 seconds and it terminates only its own remaining child
processes. Scheduling changes the read and contention counts across runs.

## Recorded POSIX results

[The complete machine-readable report](artifact-online-validation-2026-10-11.json)
contains the unrounded measurements. The published script was rerun successfully
after extraction from the initial experiment. The following numbers are from
that rerun on WSL with a local Linux temporary filesystem:

| Measurement | Reader 0 | Reader 1 |
| --- | ---: | ---: |
| Successful SHA-verified reads | 156 | 156 |
| Protected busy observations | 4 | 4 |
| Payload bytes read | 654,311,424 | 654,311,424 |
| Corrupt reads | 0 | 0 |
| Process peak RSS (KiB) | 44,096 | 44,096 |

| Measurement | Migrator 0 | Migrator 1 |
| --- | ---: | ---: |
| Completed offload/restore cycles | 6 | 6 |
| Actual released bytes | 25,165,824 | 25,165,824 |
| Protected busy observations | 92 | 254 |
| No candidate / live pin observations | 23 | 27 |
| Inventory bytes read | 180,355,072 | 213,909,504 |
| Inventory time (seconds) | 5.497903 | 6.514997 |
| Transfer / verification payload bytes read | 276,837,576 | 276,837,576 |
| Transfer / verification time (seconds) | 8.306920 | 8.311112 |
| Process peak RSS (KiB) | 44,096 | 44,096 |

The readers verified 1,308,622,848 bytes (1,248 MiB) in total. Twelve actual
offload/restore cycles released 50,331,648 bytes (48 MiB). The final local object
matched the original SHA-256 and all business tables matched the pre-soak
baseline exactly. Concurrent work took 27.309756 seconds; the entire script,
including the separate policy measurements, took 37.066892 seconds.

The aggregate RSS of the parent and four child processes, sampled every 20 ms,
peaked at 199,844 KiB (195.16 MiB). Each child also recorded its own `ru_maxrss`.
Sampling can miss short peaks; the aggregate value is not a memory upper bound.

| Public policy phase, 16 MiB object | copy | offload |
| --- | ---: | ---: |
| Configured rate per invocation (B/s) | 33,554,432 | 33,554,432 |
| Inventory bytes read | 16,777,216 | 16,777,216 |
| Inventory time (seconds) | 0.502130 | 0.501775 |
| Copy / verification / release-check payload bytes read | 83,887,205 | 184,551,632 |
| Measured payload I/O time (seconds) | 2.508539 | 5.508937 |
| Actual released bytes | 0 | 16,777,216 |
| Final policy state | complete | complete |

The meter includes repeated payload reads, including final release checks; it
does not measure physical device writes. The limit is per invocation, so two
active lanes may together consume twice the configured rate. Actual release
means confirmed deletion of the final local hardlink in that operation; it does
not promise the same instantaneous filesystem free-space increase.

## Native Windows verification

The same fixed revision was exported with `git archive` to an isolated writable
checkout on Windows 11 build 26100, local NTFS, using CPython 3.12.13. The system
temporary path and the managed worktree were not writable to that Python
process, so `TEMP`, `TMP`, and pytest's base/cache directories were set to a
writable task directory. The older environment lacked `jsonschema`; it was
installed into a separate test dependency directory. No test assertion, lock,
filesystem operation, or product implementation was replaced.

The selected native run covers these files:

```text
tests/test_artifact_coordination.py
tests/test_artifact_online.py
tests/test_artifact_policy.py
tests/test_artifact_review_target_generation.py
tests/test_artifact_review_regressions.py
tests/test_artifact_transfer.py
tests/test_artifact_catalog.py
tests/test_snapshot_external_artifacts.py
tests/test_artifact_groups.py
tests/test_artifact_online_contract.py
tests/test_archive_snapshot.py
tests/test_archive_recovery.py
tests/test_snapshot_e2e.py
tests/test_snapshot_storage.py
tests/test_migration_preservation_baseline.py
```

This includes real `LockFileEx` shared/exclusive locks across spawned processes,
two readers, a killed reader and ASR child, concurrent restore/migration,
publication fencing, all three final target-generation corruption windows,
policy disable/restart, catalog installation with a writable fsync descriptor,
split roots, external-object full snapshot save/check/restore, and preservation
of business history. The consolidated native run completed with **216 passed,
1 skipped in 113.71 seconds**, with no failures or setup errors. The one skip
was `test_archive_snapshot.py`'s symlink scenario because that Windows account
cannot create symlinks. This does not qualify symlink or network-filesystem
behavior on Windows. The native test result is also included under
`native_windows` in the JSON report; the POSIX soak's limitations describe its
own run, while this later test invocation supplies the native evidence.

To repeat the native run in a writable checkout with development dependencies,
set `TEMP` and `TMP` to a writable directory when necessary, then run
`python -m pytest` with the files listed above, `-q -rs`, and a unique writable
`--basetemp`. No platform-specific test assertions were bypassed.

## Independent review and limits

An independent reviewer approved the final generation fix after 59 focused
tests passed in 24.43 seconds; an earlier unchanged-domain set passed 166 tests.
Deleting the final generation comparison made the independent
`before-deletion-guard` regression fail. Reversing the post-read comparison made
the normal offload/restore preservation test fail. This demonstrates that the
specific guards are exercised; it is not a project-wide mutation score.

The soak is a bounded twelve-cycle test, not hours or days of production load,
and uses one object rather than a large catalog. Windows has a separate native
regression run; the multi-cycle RSS/rate soak above is POSIX-only. Model behavior
and external media services use test doubles. Space reservation is cooperative
admission control based on declared sizes and configured download estimates,
not a filesystem hard quota. External writers and an underestimated download
bitrate can still produce real I/O failures.

Use the explicit small-scope rollout instructions in
[artifact-storage.md](artifact-storage.md). Keep the first production policy
limited to one part, one lane, and `copy`; evaluate its own measured storage and
I/O before explicitly choosing `offload`.
