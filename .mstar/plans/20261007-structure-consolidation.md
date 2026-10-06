# Repository structure consolidation

Approved scope: implement the repository structure assessment in full. The operator
explicitly waived compatibility with old internal import paths and private helpers.

## Delivery

1. Bound fixture staging to packaging inputs; reject destinations inside the source.
   Consolidate temporary output rules and retain machine environments locally.
2. Add a repository entry point and a current architecture guide. Reduce the product
   README, preserve historical material with explicit dates, and index durable evidence.
3. Move shared test builders and fakes to `tests/support`; remove test-module imports.
   Remove CLI private re-exports and dispatch through concrete command modules.
4. Split SQLite repositories, ASR processing, coordination and search by responsibility.
   Move common cue types and validation rules out of their consumers; remove dependency cycles.

## Invariants and verification

Preserve transaction boundaries, acquisition evidence, atomic bundle publication,
manifest replay, queue predicates, recovery behavior and isolated wheel installation.
Update all in-repository callers and tests to the new ownership boundaries rather than
adding old-path wrappers. Run focused tests, the full supported Linux/WSL test suite,
compilation and structure checks. Preserve unrelated local work and media/model environments.

Work branch: `codex/structure-consolidation`.
Integration target for this plan: `iteration/20261007-structure-consolidation`, then `main`.
