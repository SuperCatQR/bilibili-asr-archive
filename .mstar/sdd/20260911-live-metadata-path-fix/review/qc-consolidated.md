# QC Consolidated — 20260911-live-metadata-path-fix

- Workflow: `20260911-live-metadata-path-fix` (standalone plan) · Plan: `.mstar/plans/20260911-live-metadata-path-fix.md`
- Review range / Diff basis: `25a11fe..a898fdf` (base = `main` at branch cut; QC tri reviewed through `5667844`, fix wave 2 `a898fdf` revalidated by seats 1–2)
- Working branch (verified by all seats): `fix/20260911-live-metadata-path-fix`, HEAD `a898fdf`, worktree clean
- Review cwd (verified): `/root/workspace/bilibili-asr-archive/.worktrees/20260911-live-metadata-path-fix`
- Harness corrections on `main` (not on the branch): `c9f820c`, `94eaee9`, `0819b91`
- Findings cleanup: `zero-residual`

## Seat verdicts

| Seat | Initial wave | After targeted re-review |
|------|--------------|--------------------------|
| qc-specialist (qc1.md) | Request Changes — 0C / **1W** / 5S / 0⚪ | **Approve** — 0C / 0W / 2S (both PM-fixed) |
| qc-specialist-2 (qc2.md) | Approve — 0C / 0W / 8S / 0⚪ | **Approve** — 0C / 0W / 3 cosmetics |
| qc-specialist-3 (qc3.md) | Approve — 0C / 0W / 10S / 0⚪ | (unchanged) |

## Gate decision: **Approve** (plan-level Approve is issued by the QA gate next)

The single Warning (seat 1, F-001) was a **tracked-knowledge contradiction**: `normalized-metadata-stack.md`
still asserted the "anonymous anti-bot rejection" claim that this plan's §Problem D1 declares invalid, while
the plan itself is tracked on `main`. It was fixed PM-side (knowledge doc rewritten with the accurate
risk-control statement + three transport/proxy/call-shape bullets + an explicit dated invalidation note;
plan §Durable Roadmap sentence corrected; plan Task-2 fixture deviation disclosed; spec protocol block
completed) and committed as `c9f820c`; seat 1 revalidated it as resolved.

All three seats independently re-derived D1–D4 from the **installed pinned sources** (not from the L1/L2
reports), confirmed the delivered contract is behaviourally intact (DTOs, 4-method protocol, bounded error
taxonomy, pagination/cursor semantics, repository, schema), confirmed **test non-vacuity** for every fix
(dm re-enabled, `w_webid` omitted, page-size revert, proxy not applied, dependency declaration removed —
each fails a test), and confirmed the recorded live evidence is genuinely branch code (`conftest.py` puts the
worktree `src` ahead of the control venv's editable install; control `main` still holds `PAGE_SIZE = 100`).
Seat 3 additionally audited the lockfile delta: zero removal lines, sha256 sdist + 21 wheels including
`manylinux2014_aarch64` (the host architecture).

## Fix waves covered by this consolidation

- **Product wave 1** `5667844` — Task-4 I1 (docs page-size narrative reconciled) + M1–M5 (documented `-s`,
  credential channel, test comment alignment, worktree-relative paths, `.env.example`) + Task-5 minors
  (`config.py` comment, seam literal). Revalidated Approve by the two seats that raised them.
- **Product wave 2** `a898fdf` — tests + docs only, behaviour-free, +9 test cases (suite 894 → **903 passed,
  2 skipped**): live-smoke anonymous arm restricted to the documented bounded codes (with positive/negative
  controls), fake-endpoint mirror **parity test against the installed pin** + "dm is the only override"
  test, fake `set_proxy` signature parity, packaging test now asserts the pin version, stale test docstring,
  page-size bound documented, proxy-globality/"force direct" documented, achieved live happy path recorded.
- **PM harness edits** `c9f820c` / `94eaee9` / `0819b91` — knowledge doc, spec, plan, compass, snapshot,
  status register; all committed on `main` so nothing rides the plan-Done commit (QC2 F-006 verified from
  the committed tree).

## Open items at gate close (all cosmetic, dropped per the zero-residual nit rule)

1. `tests/test_bilibili_api_gateway.py` module docstring still calls the packaging test "the one exception"
   to needing the installed distribution (there are now four). Prose-only; polish when that file is next touched.
2. An invalid-argument parametrization in the same file still names `100` (inert; the argument is invalid
   regardless of value).
3. `.env.example`'s proxy block does not repeat the "blank counts as unset" caveat now documented in
   docs/README.

None of the three touches shipped behaviour, the delivered contract, or the acceptance surface.

## Hand-off to the mandatory QA gate (L4 owns these)

1. Clean-install proof: `uv lock --check` no-op and a fresh `uv sync` (scratch env) that can import the HTTP
   backend and the pinned distribution.
2. Full offline suite at `a898fdf` — expect **903 passed, 2 skipped**.
3. Opt-in live smoke re-run **from the worktree package dir** (so `conftest`'s `sys.path` insert wins over the
   control venv's editable install, which points at pre-fix `main`) **with `-s`/`-rP`** on the first attempt,
   credential + `BILI_HTTP_PROXY` present: record the anonymous bounded-failure branch, the credentialed
   happy path (expect `outcome=limited`, one page, real rows, cursor advanced), and any bounded blocker.
4. `curl-cffi` 0.16.3 lock/hash sanity.
5. DoD mapping over the plan's 8 acceptance criteria + residual check (register empty).
