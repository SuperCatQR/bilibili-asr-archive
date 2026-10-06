# Independent current burndown review

Reviewed primary `origin/main..c327671f9d11383a5dcc58b54c8a2a426a408bec` on
2026-10-06, scoped to metadata bounded caching, shared usable-audio resolution,
archive target refusal, and store-qualified publication recovery. Did not
evaluate other agents' unmerged #49/#50 changes or repeat the previously
recorded broad suites.

## P2 found and repaired: malformed unrelated manifest page aborts pending

`cli/run._store_pending_rows` validates recovery identity in the first pass,
but the second pass hashes `(bvid, page_index)` for every manifest row before
checking its stage. Manifest replay permits a list-valued `page_index`. Thus
even an unrelated `meta_ok` row with `page_index=[]` raises
`TypeError: unhashable type: 'list'` and aborts the entire pending scope.
A minimal read-only reproduction confirmed both manifest validation acceptance
and the exception with an empty store queue; no network or archive write was
needed for that reproduction.

The repair retains the first pass's validated recovery candidates and reuses
them in the second pass. The acquisition queues and store-part qualification
remain unchanged. Added two negative controls, for unrelated `meta_ok` and
recovery `subtitle_done`, each alongside a valid store-backed recovery row.
Both malformed rows are ignored while the valid recovery row remains selected.

Focused WSL verification: **4 passed in 4.63 seconds**:

```sh
PYTHONPATH="$PWD/src" /home/chosenecho/.venvs/bili-asr-pipeline/bin/python -m pytest -q \
  tests/test_runtime_burndown.py::test_publication_recovery_requires_a_store_part_and_ignores_manifest_only \
  tests/test_runtime_burndown.py::test_malformed_manifest_page_does_not_abort_store_pending_selection
```

## Other reviewed boundaries

No additional blocking product finding in the specified changes. The metadata
LRU keeps independent page-local observations, so eviction does not drop answers
from a page larger than the cache. `None` remains degraded rather than an empty
tag observation, and each resumed run starts a fresh cache. Page-local author
updates preserve the last label on nameless pages; unchanged labels preserve
their timestamp.

Usable-audio resolution shares the confinement and nonempty predicate across
download, coordinator, and pilot routes. An empty configured-root stub no
longer shadows a legacy copy. Returned absolute paths are paired with the base
that derived their relative name, and consumers re-confine at use.

POSIX publication checks every existing artifact target before invalidating
the marker and replacing bundle contents; marker-specific refusal remains in
`_invalidate_marker`. Windows also preflights artifacts and the marker. The new
per-artifact tests verify refusal preserves the marker and other bundle bytes.

One nonblocking test gap was reported to the root agent and then repaired: Windows marker
preflight now raises `archive target is not a regular file`, while an existing
marker test expects `marker is not a regular file`. That test's initial symlink
creation can skip the subsequent directory case on hosts lacking privilege.
The safety refusal works, but a privileged Windows run would expose the message
assertion mismatch. Marker preflight now preserves the existing marker-specific
error text, and an independent marker-directory test verifies all artifact bytes
remain unchanged without requiring symlink privilege.

Focused WSL marker tests: **2 passed in 1.32 seconds**, selecting
`test_marker_directory_is_refused_without_symlink_privilege` and
`test_write_archive_rejects_marker_symlink_and_nonregular_without_touching_target`.
The native Windows run using the existing primary `.venv/Scripts/python.exe`
could not reach either test body: temporary-directory/fixture creation failed
with `WinError 5` in this worktree, including after redirecting `TEMP`/`TMP` to
its ignored `.test-tmp`. This is an environment-limited run, not a passed or
skipped native verification. No broad suites were repeated to investigate it.
