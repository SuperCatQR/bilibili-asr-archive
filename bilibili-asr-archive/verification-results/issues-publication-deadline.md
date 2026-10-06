# Issue 50: supervised publication deadlines

The complete original obligation is `.mstar/projects/_default/issues-register.md`, I-000029. GitHub truncates the title and the remote body contains only impact and `Acceptance: defer`; the full original has four items. No acceptance requires unsafe lock release while a kernel-blocked writer remains alive.

- (a) SQL part selection bounds transcript reads; pending uses bounded keyset batches. Candidate limit and pending regression tests cover this.
- (b) CLI publication now runs entirely in a lock-owning process, supervised before artifact-root probes and writer-lock acquisition. An authenticated localhost channel advances setup, per-candidate, and final-snapshot deadlines; stdout does not renew them. Default `--io-timeout-seconds 60` is finite and positive. On expiry the invocation stops with exit 1. Progress and summary output flush when piped. Windows nonblocking byte-range lock refusal is normalized to `archive_busy` only at the lock syscall, preserving genuine open-permission errors.
- (c) artifact product keys share the canonical tuple, pinned by identity assertions.
- (d) projection and entry construction errors are per candidate. Real corrupt store tests cover a fourth source kind, invalid identity and overflowing publication date, including later candidate continuation and pending limits.

The supervisor never releases a worker-owned lock. POSIX terminates the process group; Windows terminates the launcher tree with taskkill and bounded fallback. Explicit cleanup waits total at most 0.2 seconds on POSIX and 0.6 seconds on Windows. A kernel-uninterruptible worker can retain its lock until it actually exits: other writers correctly remain busy. Timeout does not imply rollback or absence of completed writes. Rerunning after mount recovery reconciles complete bundles and retries incomplete ones. Process creation and blocked parent terminal output are outside the deadline. Direct Python handler callers retain synchronous behavior. No real uninterruptible kernel mount experiment is claimed.

## Verification

- Windows native Python: `tests/test_publication_supervisor.py`: **16 passed in 9.13s**.
- WSL Ubuntu pipeline Python: same real-subprocess suite: **16 passed in 13.68s**.
- Tests cover normal publication/output, root validation stall, artifact write stall, manifest snapshot stall, lock ownership and competition, re-acquisition after kill, phase renewal, stdout non-renewal, terminal/invalid protocol, invalid deadlines, missing Windows tree killer fallback, and simulated unreapable worker bounded cleanup.
- Independent review found no remaining P1/P2 blocking defect. Full suite CI is the PR merge gate; final CI result is retained on the pull request.
