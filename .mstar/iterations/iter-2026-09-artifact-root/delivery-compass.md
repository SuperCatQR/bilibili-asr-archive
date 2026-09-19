---
iteration_id: iter-2026-09-artifact-root
start_date: 2026-09-19
status: active
iteration_base_branch: main
target_branch: main
plans: []
---

# Delivery Compass — iter-2026-09-artifact-root

**Feature (user request, 2026-09-19):** the location where the pipeline writes its **audio and products**
becomes configurable, so an operator can put them on `/mnt/123pan` while the repository, the working tree
and the project state stay where they are. Audio is to be **retained indefinitely**.

**Status: direction CONFIRMED by the user 2026-09-19 — the six decisions are recorded in §2 and the spec
is written against them. The compass locks at the end of Phase 1 (after the plan exists).**

## 1. What exists today (recon, read-only, 2026-09-19)

Everything lives under one `--archive-root` (`cli.py:28` `DEFAULT_ARCHIVE_ROOT = "archive"`), split into
two kinds of thing that this iteration must separate:

| Kind | Paths | Nature |
|---|---|---|
| **Products** | `{root}/audio/` (`audio.py:35`, `:202`), `{root}/transcripts/{srt,txt,md,raw}/` (`archive.py:466-471`), `{root}/subtitles/` | the outputs the user wants relocatable |
| **State** | `{root}/manifest/manifest.jsonl`, `{root}/archive.db` (`database.py:40`, opened below the root), `{root}/coordinator/` (attempts, locks) | a SQLite database, an fsync-per-append JSONL and lock files — see the placement hazard |

Three hard constraints make "just add a flag" wrong:

1. **`audio.py:187` asserts the audio directory IS `<archive_root>/audio`** — the location is pinned in code, not policy.
2. **Audio is confined to the archive root by an explicit safety invariant**: `path_policy.confined_audio_path`
   plus `coordinator.py:568` / `:617` raising `OSError("audio path outside archive")`, with descriptor-anchored
   opens (`path_policy.py:32-50`, `O_NOFOLLOW`) that deliberately refuse a symlinked `audio/`.
3. **Two subsystems assume the path shape**: `audio_budget.py:34` measures `root/audio`, and
   `audio_reclaim.py:16-36` builds its candidates as `audio/{stem}.{m4a,flac}`.

**Placement hazard the design must respect** (evidence from the closed plan's QC): `archive.db` is SQLite
opened `isolation_level="DEFERRED"` with no WAL, and the manifest appends with an fsync pair per row
(`manifest.py:186-220`). A FUSE/WebDAV mount cannot carry POSIX locks to the cloud, so **state must not be
relocated onto the network mount**; products may be.

## 2. Decision register (CONFIRMED by the user, 2026-09-19)

| # | Decision | **Decided** |
|---|---|---|
| **D1** | What becomes configurable | **One artifact root** covering audio + transcripts + subtitles. State (manifest, `archive.db`, coordinator) stays at the archive root. |
| **D2** | Mechanism and precedence | **CLI flag + environment variable, the flag wins.** Unset reproduces today's behaviour byte-for-byte. |
| **D3** | Naming | **`--artifact-root` / `BILI_ARTIFACT_ROOT`** (recommendation adopted by the PM; nothing is committed yet, so a rename is still free). Iteration slug `artifact-root`. |
| **D4** | The confinement invariant | **Re-base the guard onto the configured artifact root** — an artifact root outside the state root becomes legal, while the descriptor-anchored guarantees stay: each configured root opens with `O_NOFOLLOW`, no symlinked target directory is followed, and a path escaping its own root is still refused. |
| **D5** | Audio retention | **Promote to a first-class flag, retained by default.** `BILI_KEEP_AUDIO=1` stays honoured as the existing escape hatch. |
| **D6** | Migration | **None.** Unset = today's paths; an existing archive root keeps working, and legacy relative `audio_path` values in an existing manifest keep being honoured by every reader. |

## 3. Non-goals (proposed)

- No relocation of **state** (`manifest/`, `archive.db`, `coordinator/`) onto a network mount — the SQLite/lock
  hazard above.
- No change to the repository, the harness tree, worktrees or virtualenvs.
- No new storage schema, no second source of truth for audio state.
- No automatic cloud publication/sync: this iteration makes the **location** configurable; moving finished
  artifacts to the cloud is the operator's `rclone` step, not a pipeline responsibility.

## 4. Verification sketch (to be firmed up in the spec)

- Unset root → byte-identical behaviour to today (the existing suites are the regression evidence).
- Configured root → audio and bundles land there; `coverage`, `verify`, `export`, `coverage --quality` and
  `status` report the same inventory as with the default layout.
- The confinement guard still refuses an out-of-root path **for the configured root** (the invariant is
  re-based, not dropped) and still refuses a symlinked target directory.
- Retention: with the retain policy, a row reaching `archived` leaves its audio in place.

---

## Naming note (naming rule applied)

The codebase already calls the outputs **artifacts** (`artifact_stem`, `coverage_report`'s
`artifact_present`), and calls the single current root the **archive root**. `artifact root` therefore reads
as "where the artifacts go, when that is not the archive root" — specific, consistent with existing
vocabulary, and it does not overload "output" (vague) or "cache" (wrong: these are durable products).
Alternatives considered: `--output-root` (vague about *what* output), `--products-root` (introduces a third
word for a concept that already has one), `--artifacts-dir` (dir implies single-level).

## 5. Why the split is the whole point (context the spec must carry)

The user's target is `/mnt/123pan` — a WebDAV FUSE mount. Products belong there; **state does not**:
`archive.db` is SQLite `isolation_level="DEFERRED"` with no WAL, and `manifest.py:186-220` fsyncs a pair per
append. FUSE cannot carry POSIX locks to the cloud, so relocating state would trade a correctness guarantee
for a path preference. D1's split is what makes the user's goal safe rather than merely possible.

The audio-retention decision (D5) also removes the usual reason to relocate state: nothing needs to be
pruned to reclaim space, because retained audio is a product the user wants kept.
