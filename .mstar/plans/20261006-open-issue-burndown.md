# Open issue burndown after PR 221

User authorizes concurrent fixes, pull requests, and merging until open issues are resolved. PR 221 merged the tested tree into main; retain pending CI results and repair any failures.

Audit all 113 initial open issues against current source and exact acceptance criteria. Historical ledger issue numbers are not authoritative. Close only when current evidence establishes the requested behavior or the issue explicitly permits a recorded decision. Preserve external validation requirements honestly.

Lanes after this plan is committed:

- Storage: remaining transaction/validation contracts and metadata cache/refresh issues 69, 70, 75, 90, 92, 93; examine artifact-free acceptance options without weakening invariants.
- CLI/runtime: artifact target symlink refusal 104, artifact base attribution 48/126, corpus hashing/mount timeout 49/50, store route contract 158, and sync artifact-root operations documentation 125.
- Documentation/tests: actual outstanding source/docs mismatches 83, 164, 165, 171, 177; independent reviews 66/103; external engine issues 127/192/207 require source ownership and verified fix rather than hand-editing registers.

Use isolated codex feature worktrees and merge reviewed commits into the iteration branch. Run focused regressions for new changes and one integrated suite per completed batch. Keep credentialed network, actual GPU/model, and historical external corpus validations distinct from offline regression evidence. Keep an exact issue evidence matrix in product verification-results.

Git HTTPS is unavailable through the current host proxy. GitHub API uploads must verify the resulting tree hash matches the locally tested tree and use current remote main as parent. No unrelated worktree or runtime cleanup.
