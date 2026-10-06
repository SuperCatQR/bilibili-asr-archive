# Independent verification worker review — 2026-10-06

Reviewed c572f4b6a31d983e3b4385abdb2dd8d65266c6e5, including the worker,
publisher integration, CLI validation, read-error test adapters and recorded
publication I/O boundary. Review found one concrete P2 import-consistency issue.

The parent can import the current source through a sys.path insertion (as the
test conftest does), while a fresh `python -m` worker sees only its own import
path and inherited PYTHONPATH. In an actual WSL reproduction the parent loaded
the worktree service and the child loaded the primary checkout service through
the existing editable installation. An older installation lacking this module
would fail all otherwise valid verification attempts; another version could
apply different validation rules.

The repair passes an environment copy to Popen, prepending the import root of
the currently loaded package to PYTHONPATH. It preserves the caller's existing
environment, including Windows TEMP/TMP and any previous PYTHONPATH entries.
The path computation covers ordinary source, editable and unpacked installed
package layouts. A packaged-wheel installation was not separately exercised.

Two real-child regressions run from an unrelated working directory, with
PYTHONPATH absent and with a deliberately incompatible shadow package. They
check the imported service's actual file identity, then run the normal worker
against a real archived bundle, and assert the parent environment is unchanged.

Validation from this worktree's product directory, without an exported source
PYTHONPATH:

```bash
env -u PYTHONPATH /home/chosenecho/.venvs/bili-asr-pipeline/bin/python \
  -m pytest -q tests/test_bundle_verification.py
```

Result: **11 passed in 5.02s** on WSL Python 3.12. Temporarily restoring inherited
environment behavior made both new cases fail at the child file-identity check
(**2 failed, 9 deselected in 1.79s**); the repaired source was restored afterwards.

No additional blocking defect was identified in the reviewed process boundary.
`close_fds=True` prevents writer descriptors from reaching this fresh process;
the existing POSIX real-child test checks an explicitly inheritable descriptor.
Windows uses CREATE_NO_WINDOW and inherits normal environment variables, with
no new temporary-directory override. The in-process read-error adapter keeps
specific old monkeypatch tests meaningful; separate real-child tests exercise
hashing, same-size/same-mtime mutation, timeout and continued verification.
Native Windows worker execution was not repeated in this review.

The deadline bounds waiting for the read worker plus bounded cleanup, subject
to the documented process-creation limitation. Kernel-blocked killed workers
can remain alive and are retained with a capacity limit. This does not establish
a complete writer deadline: SQLite, publication writes, fsync and manifest
updates remain outside this boundary. No wider timeout claim is made.
