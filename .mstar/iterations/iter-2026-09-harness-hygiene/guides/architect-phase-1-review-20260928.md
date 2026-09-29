# Architect Phase 1 review (2026-09-28) — the four gaps, settled

> Narrative record of the architect seat's Phase 1 review for `iter-2026-09-harness-hygiene`.
> The rulings themselves are **D9–D12** in `../delivery-compass.md`, and each plan carries its
> own `### Architect ruling (Phase 1 review 2026-09-28)` section; where this file and those
> disagree, they win. Moved here from the compass on 2026-09-28 (writing-specialist, §1.6) —
> `iteration-artifact-boundaries.md` keeps long-form exploration prose out of
> `delivery-compass.md` and links to it instead. No content changed in the move.

The hygiene pass surfaced four gaps it could not settle inside itself. The first three came to this
review as open questions (Q2–Q4 plus Q1, which the product-manager seat ruled); all are **ruled**
(D9–D12 in `../delivery-compass.md`) and verified against the disk rather than accepted from the
gap text — where the gap text was wrong, the file was corrected and the correction is named.
Nothing is left as a marker.

1. **The register's write path** → **D9**. The gap text said the engine's replacement writer is
   retired and the `persist` write verbs refuse. **Half right, and the wrong half mattered:**
   `persist residuals` **is** a writable coordinated kind on the installed 3.11.2 build and takes a
   CAS token; `grep -c "is the only findings authority"` over the installed dist returns **0**. The
   refusal is the register's own 144 violations, because `persist` validates before put — a
   chicken-and-egg the producer of the corrected document has to break, and D9 says how. What *is*
   genuinely absent on this build is `store` / `issue` / `catalog` (exit 1, `unknown command`), so
   migrating to `store.db` is **not available here** — the engine source mirrors that it shouldn't
   be, since `packages/cli/src/index.ts:6403-6410` registers all three.
2. **Worktree ownership metadata** → **D10**. The planner refuses **7** `foreign-worktree` and **2**
   `dirty-worktree` over the 10 `.worktrees/*` checkouts — the gap text's "7 refuses" counted only
   the first class. The metadata gap is **historical**: the engine writes `metadata.working_branch`
   at handoff and at `prepare` today, so this is not a contract the engine is missing. And
   `--worktree <path>` **does** assert ownership where the checked-out branch is recorded by exactly
   one row — reproduced, flipping `.worktrees/20260928-metadata-r3docs` from `foreign-worktree` to
   `remove | … | cleanup.remove.merged`. Plan B should use that mechanism instead of arguing.
3. **The published-vs-local boundary** → **D11**. Verified: 41 tracked under `.mstar`, **11**
   non-conforming by the old three-exception rule — of which **5 are rule-consistent under the
   amendment** (iteration `specs/` drafts) and **6 are frozen debt**. Attributed **7 / 2 / 2**
   to `2696711` / `d1c9600` / `cefed49` rather than "the 11 added by three commits, one day
   after the cleanup" (`18e8119` is 2026-09-25; the last two re-adds are 2026-09-28).
   `.mstar/AGENTS.md`'s own "Five kept files … 166 such references" was **not reproducible** at
   any commit checked and has been replaced with the reproducible pair (**4 files / 6
   references** at `371693b`). The ruling fixes the boundary with one deliberate widening
   (iteration contract drafts, which the published set cites by exact path) and enforces it in
   two halves: **plan A** asserts it as a ratchet (new out-of-set paths fail; the six are
   tolerated and may only shrink), **plan B Task 4** makes it real in `.gitignore` — which had
   never carried the amendment, so before this review the rule existed only in prose. The
   split exists because this repo has no CI (`.github/` absent) and no hook infrastructure
   (`core.hooksPath` unset) to hang enforcement on.
4. **The deletion archive** → **D12**, the fourth gap: `.tmp/deletion-records/` is the sole
   surviving copy, `.tmp/` is gitignored and swept by design, and plan B's exclusion was prose in a
   plan file. The ruling publishes it into the tracked product `docs/archive/` tree — which is what
   makes the protection structural, since the bytes then survive any sweep by construction — and
   keeps the `.tmp/` copy as the working original. A byte-asserting test was considered and
   rejected on contract grounds (plan B is Git-only; plan A's checker is scoped to the documents the
   engine reads); the residual risk is carried as plan B **D-4** rather than papered over.
