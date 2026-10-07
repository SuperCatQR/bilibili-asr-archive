# Issue 49: finite strict verification read budget

Date: 2026-10-06. Follow-up to the publication read-isolation change.

## Result

The default `publish-transcripts` invocation can no longer content-read an
unbounded published corpus: it has a shared finite **256 MiB** verification
allowance. `--verify-read-budget-bytes` permits an explicit positive integer
override. This applies to normal and pending publication, both existing bundle
checks and post-write confirmation, counting marker bytes and each artifact's
actual bytes returned from `os.read`. Each read syscall's requested size is
clamped to the remaining allowance. Size/mtime estimates do not decide usage
or completeness; all successful decisions still hash every artifact.

On exhaustion the command reports a bounded budget failure, exits 1 and stops
later candidates. It preserves an existing unverified bundle and does not
claim it already published. A post-write exhaustion records no manifest
completion row. Earlier fully confirmed publications are retained. Operators
can explicitly increase the budget or narrow the part selector.

The parent reserves the full remaining allowance before sending a worker
request. It refunds only reported unused bytes from a valid response; worker
timeout/invalid response retains the full reservation because read usage is
unknown. A surviving read-only worker can therefore never share the same
allowance with a later worker. Exact-limit EOF confirmation may conservatively
refuse verification, which is documented; it never reads over budget.

The prior report's #49 performance gap is superseded by this finite-default
implementation. It does not eliminate the intrinsic cost of strict hashes;
it makes unrestricted corpus reads an explicit override rather than a default.
#50 remains partially open, with no claimed whole-candidate write deadline.
Budget covers logical returned verification bytes, not kernel readahead,
SQLite reads or output writes.

## Verification

WSL Ubuntu-24.04, Python 3.12 environment:

- Bundle verification, CLI publication, read failures and pending publication:
  **63 passed** (96.91s).
- Candidate-limit, read-failure and pending selection regression suite:
  **47 passed** (81.97s).
- Final complete bundle-verification and CLI-publication suites after the two
  additional refusal regressions: **34 passed** (35.16s).

Native Windows Python worker checks:

- Budget/deadline/content-tamper checks: **10 passed**.
- Final budget/allowance/invalid-response checks, including post-write manifest
  refusal: **7 passed**.

The budget tests verify actual marker plus artifact bytes against a known
bundle, a single-bundle 17-byte cap, cumulative second-worker exhaustion,
timeout reservation, invalid-response refusal to refund, preservation of an
existing bundle, stopping later candidates, and no completion row when
post-write verification exhausts its allowance. Windows and POSIX archive
readers both use the counted `os.read` path.

Independent review also found that a worker launched with `-m` must be pinned
to the parent package rather than resolving an unrelated installed package.
That source-pinning correction is supplied in separate commit
`0b21a1983b078c43ae00bae4caa862ca74c63ccb` and must be integrated with this change.

The primary checkout integrated both changes. Native Windows publication,
read-failure, part-limit, pending and worker tests: **81 passed, 2 skipped in
55.39 seconds**. The source mismatch regressions pass without exporting
PYTHONPATH. PR 222's preceding final CI completed with **2795 passed, 61 skipped**.
