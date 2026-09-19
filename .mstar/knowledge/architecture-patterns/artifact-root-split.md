---
module: bili-asr artifact storage
date: 2026-09-19
problem_type: architecture_pattern
category: architecture-patterns
severity: medium
plan_id: 20260919-artifact-root
applies_when:
  - making the location of a pipeline's durable outputs configurable
  - deciding whether a store may live on a network or FUSE mount
  - re-basing a path-confinement guard onto an operator-chosen root
  - resolving a recorded relative path that may sit under more than one root
  - adding a new artifact family or a second configured root
tags:
  - artifact-root
  - products-vs-state
  - path-confinement
  - ordered-base-read
  - no-migration
---

# Relocatable products, state that stays put

## Context

An operator wants the archive's bytes on a WebDAV/FUSE mount (the operator's `123pan` mount) while the repository, the
worktrees and the project state stay on local disk. The pipeline has one root today (`--archive-root`), and
it holds two kinds of thing that only one of which can move:

| Kind | Paths and writers | Why it may — or may not — move |
|---|---|---|
| **Products** | `{root}/audio/{stem}.m4a` / `.flac` (`bilibili-asr-archive/src/bili_asr/audio.py:174-267`, staged and renamed inside the audio directory `:239-267`); `{root}/transcripts/{srt,txt,md,raw}/{stem}.*` (`archive.py:452-488`, published by `_publish_bundle` `:220-243`); `{root}/subtitles/raw/{stem}.json` and `{root}/transcripts/srt/{stem}.srt` (`subtitles.py:83-164`) | the outputs the operator wants on the mount; every publish is a stage-and-`os.replace` inside one directory descriptor, so a different filesystem adds no cross-device rename |
| **State** | `{root}/manifest/manifest.jsonl` (append-only JSONL, one fsync pair per append: `manifest.py:179-190`, snapshot replace `:194-221`); `{root}/archive.db` (SQLite, deferred isolation, no WAL: `bilibili-asr-archive/src/bili_asr/storage/database.py:40`, `open_database` `:196`); `{root}/coordinator/` (attempts ledger and `archive-writer.lock`, `coordinator.py:72-95`); `{root}/meta-cursor.json`, `{root}/scheduler.json`, `{root}/run-ledger.jsonl`, `{root}/campaign.json`, `{root}/search.db` | a FUSE/WebDAV mount cannot carry POSIX locks to the cloud, and the manifest's durability *is* the fsync pair on each appended row — relocating state trades a correctness guarantee for a path preference |

Three shipped assumptions make "just add a flag" wrong, and each is the reason for one part of the design:
the audio write path derived its base from the requested path or the store's root
(`audio.py:133-172`), audio is confined to its root by an explicit descriptor-anchored guard
(`path_policy.py:32-111`), and two subsystems derive paths from the root shape
(`audio_budget.py:32-45`, `audio_reclaim.py:24-37`).

## Guidance

1. **Split by kind, and let the hazard choose the boundary.** Products relocate; state
   (`{root}/manifest/`, `{root}/archive.db`, `{root}/coordinator/`, the cursor/scheduler/ledger/campaign/search sidecars) stays at
   the archive root. The boundary is not a convenience: it is the set of paths whose correctness depends on
   POSIX locking and on directory/file `fsync` semantics that a network mount does not promise. State-side
   mechanics are in [operational-sidecars.md](operational-sidecars.md); the product side is what this doc
   covers. A consequence to state rather than discover: the products' own directory `fsync`s are *also* a
   mount requirement (`path_policy.py:51`, `:182`, `:196`, `archive.py:99-106`, `:217-243`,
   `audio.py:239-267`), so an fsync-hostile mount passes the one-time validation and fails per row — the
   operator docs say so and no fifth refusal line pretends otherwise
   (`bilibili-asr-archive/docs/artifact-root.md:26-33`).

2. **One value object, one resolution site.** `ArtifactRoots` (`artifact_root.py:95-136`) carries both
   roots; libraries accept it keyword-only and default to the identity case (`artifact_roots=None` →
   `ArtifactRoots.of(archive_root)`), and the CLI resolves it exactly once in `main()` between `parse_args`
   and the writer-lock block (`cli.py:3490-3503`). Resolving there, rather than inside a handler, is what
   keeps a refused invocation from creating `{archive_root}/coordinator/` (the lock's documented side
   effect) and keeps a handler's broad `except Exception` from swallowing the reason. No library module
   resolves configuration itself, and no library reads the environment — the environment is read at the
   boundary and passed down (`resolve_artifact_root` `:164-181`, `resolve_keep_audio` `:182-198`, both pure
   over a mapping).

3. **Writes resolve on one base; reads probe an ordered pair.** `write_base`
   (`artifact_root.py:127-130`) is the single base every write uses, so a write never picks its base by
   asking which directory exists. `read_bases()` (`:132-136`) returns `(artifact_root, archive_root)` when a
   root is configured and `(archive_root,)` otherwise; every reader walks that order and validates each
   candidate **at its own base** with its own family's guard — audio through
   `path_policy.confined_audio_path` (`:78-111`) via `resolve_audio_path` (`artifact_root.py:272-300`),
   bundles through `archive.archive_bundle_complete` (`archive.py:170-206`), and the reader-side containment
   checks each in their own module (`coverage_report.py:470-496`, `quality.py:347-357`,
   `integrity.py:211-232`, `export.py:203`, `search_index.py:174-214`). The per-family guards stay
   un-unified on purpose: sharing the base *list* is the new rule, rewriting two security mechanisms is not.

4. **Keep the recorded paths root-relative; that is what makes "no migration" honest.** `audio_path`,
   `srt_path`, `txt_path`, `md_path`, `raw_path` keep their shipped shape (`audio.py:284-322`,
   `archive.py:488`, `subtitles.py:164`), so the manifest's bytes are unaffected by the feature and no row
   has to remember which root it was written under. Nothing durable records the configured root: a later run
   with a different root neither rewrites nor invalidates earlier rows, and the tool never discovers or
   remembers a previous root. Reads probe the configured root first and fall back to the archive root, so an
   archive written before the switch keeps resolving on day one — that probe, not a migration step, is the
   compatibility mechanism.

5. **Re-base the guard; do not weaken it.** `bilibili-asr-archive/src/bili_asr/path_policy.py` is already root-parameterised and is not
   modified at all — only the root handed to it changes. Each configured root keeps the whole
   descriptor-anchored property set: `O_NOFOLLOW|O_DIRECTORY` on the root and on `{root}/audio/`
   (`path_policy.py:32-57`), `dir_fd`-relative component opens with `O_NOFOLLOW` (`:60-76`), the
   `fstat` regular-file check (`:64-69`, `:101-106`), and the inode-identity check before unlink
   (`:142-199`). What the guard stops refusing is exactly one thing — "an artifact that lives outside the
   archive root" — which was never a security property but a consequence of there being a single root.
   The identity case is a no-op by construction: a configured value lexically equal to the archive root
   yields one base and no further validation (`artifact_root.py:123-125`, `cli.py:3490-3493`).

6. **Keep the configured path lexical and refuse a symlinked root up front.** Resolution is
   `expanduser` + `abspath` only (`artifact_root.py:155-162`), never `realpath`: resolving first would
   defeat the `O_NOFOLLOW` check the whole design rests on. The cost is disclosed rather than hidden — a
   symlinked root (and a symlinked target directory) is refused; pass the real path.

7. **Say what ordered probing costs.** First hit wins, and each base is judged independently, so a
   candidate that the configured root *refuses* (a symlinked audio file under `{root}/audio/`, `path_policy.py:101-106`) is
   skipped in favour of a valid copy at the archive root: a tampered entry in the configured root can be
   masked by a legacy copy. Nothing insecure follows — no symlink is followed, and the returned path is
   validated against its own base — but the shadowing is part of the rule, not an edge case to discover.
   The alternative rule ("a refusal at the configured root is final") was rejected because the audio guard
   returns `None` for both "refused" and "missing" under `require_exists=True` (`path_policy.py:78-111`),
   so it would buy a narrow signal at the price of two resolution rules for one concept.

8. **One writer lock, archive-root-scoped.** The lock protects **state** — the manifest's
   read-modify-append and the SQLite writes — while artifact publication is per stem, staged inside its own
   directory and atomically replaced. So no second lock is added on the artifact root, and the supported
   configuration is **one artifact root per archive root** for concurrent writers. Two archive roots
   sharing one artifact root is out of contract and undetected; the shared fixed staging directory name
   fails loudly rather than interleaving (`archive.py:228-230`).

## The operator surface, and the four refusal lines

`--artifact-root <path>` (or `BILI_ARTIFACT_ROOT`) is added only to the commands that resolve an artifact
path — eleven of them (`cli.py:156`, `:180`, `:263`, `:317`, `:365`, `:411`, `:462`, `:468`, `:494`, `:506`,
`:557`); the six commands that touch no artifact path carry neither flag, because an accepted-but-ignored
flag is a false statement in the interface. Precedence is flag > non-blank environment > archive root, where
a blank counts as unset at either level and `~` is expanded (`artifact_root.py:164-181`).

An unusable configured root is a **refusal** — exit 1, one named line on stderr, no report body — never an
empty inventory and never an auto-created directory (`artifact_root.py:224-270`, `cli.py:3490-3496`). The
vocabulary is four lines, and **each is true of the input that produces it**:

| Line | Input it is true of |
|---|---|
| `artifact root does not exist (<path>)` | nothing at that path |
| `artifact root is not a directory (<path>)` | a file, socket or device at that path |
| `artifact root is a symlink (<path>)` | a symlink at the final component (`islink` is checked before `is_dir`) |
| `artifact root cannot be opened (<path>)` | a directory that exists and cannot be opened (permission denied, erroring mount) |

The fourth exists because none of the other three is true of its input: "does not exist" and "is not a
directory" would both be false, and reusing either would weaken the pin for the case it names. Two
consequences are registered rather than papered over: a self-referential symlink in an **ancestor**
component is reported by the first line (`pathlib` ignores `ELOOP` exactly as it ignores `ENOENT`, so the
classification cannot tell the two apart), and a mount that opens but rejects directory `fsync` passes
validation and then fails per row with a raw `OSError` that is not one of the four. Both are fail-closed,
both are disclosed on the operator page, and neither is answered by inventing a fifth line or a false one
(`bilibili-asr-archive/docs/artifact-root.md:57-86`, `:136-151`).

## Why This Matters

A path preference looks like configuration and behaves like a correctness change: the moment a second root
exists, every reader and writer that used to agree by construction (there was one root) can disagree, and
the disagreement shows up as a *report*, not a crash — `verify` calling a live archive missing while
`coverage` calls the same row present, a row silently never reaching `audio_ok`, a cap that measures the
wrong device. Splitting products from state is what makes the feature safe rather than merely possible: it
keeps SQLite locking and the manifest's per-append fsync pair on local disk, while the parts that only need
POSIX file semantics move to the mount. Re-basing the guard instead of rewriting it keeps a reviewed
security mechanism byte-identical, and keeping the recorded paths root-relative keeps the manifest a no-op
for the feature — which is what lets an existing archive keep working with no migration step.

## When to Apply

- Making the location of a pipeline's durable outputs configurable while its state stays put.
- Deciding whether a store, lock file or append-log may live on a network/FUSE mount: if it needs POSIX
  locks or directory `fsync`, it does not.
- Re-basing a confinement or containment guard onto a configurable root: pass the root through, and keep
  the guard's per-component guarantees.
- Adding a new artifact family: state its write base (`write_base`) and its read rule
  (`read_bases()` + that family's own guard), and neither re-derive the root from a path nor read the
  environment inside a library.
- Not a pattern for a *second* configured root: `write_base` is singular by type, so a third root is a
  design change to the value object and to every write call site, not a new flag.

## Examples

### The declared-vs-absolute value trap (why the write rule is "one base, no probing")

`download_audio` can return a path that already exists under either base (its resumability fast path walks
`read_bases()`, `audio.py:109-131`, `:201-211`). A caller that measures that returned path against the write
base alone raises `invalid audio path` for a legitimate legacy row; the rule that holds is: **writes and
write-side re-confinement resolve on `write_base`, reads of a recorded value resolve over `read_bases()`,
and a value returned by the pipeline is paired with the base that holds it** (`cli.py:2054-2098`,
`coordinator.py:432-471`). Two commands pairing the same value differently is a defect of this family, and
the tell is the disagreement — see
[pairing-rule-travels-with-behaviour.md](../best-practices/pairing-rule-travels-with-behaviour.md).

### What the guard still refuses, per base

```text
audio/../secret.m4a      /tmp/x.m4a      audio/x.wav      audio/sub/x.m4a
```

| Input | Verdict under either base |
|---|---|
| an escaping or wrong-shaped recorded value | refused (`path_policy.py:16-29`, `:87-89`) |
| a symlinked root or a symlinked target directory | refused (`:32-57`) |
| a symlinked audio file | refused at open and at stat (`:60-76`, `:101-106`) |
| a directory, fifo or device where a file is expected | refused (`:64-69`, `:101-106`) |
| an audio file whose inode changed between validation and unlink | refused; quarantine + restore (`:142-199`) |

Pinned by `bilibili-asr-archive/tests/test_artifact_root.py:281-299` and, for the shipped single-base
cases, `bilibili-asr-archive/tests/test_persistence_scale.py:527-556`.

## Evidence

- Iteration `iter-2026-09-artifact-root`, plan `20260919-artifact-root`; contract
  `.mstar/iterations/iter-2026-09-artifact-root/specs/artifact-root-contract.md` (the products/state split
  §2, resolution §3, the write map §4, the two-base read rule §5, the re-based guard §6, the operator surface
  §9, the reader table §10).
- Implementation: `bilibili-asr-archive/src/bili_asr/artifact_root.py` (the resolution core),
  `cli.py:3490-3503` (one resolution in `main()`), `bilibili-asr-archive/src/bili_asr/path_policy.py`
  (unchanged), `audio.py:174-267`, `archive.py:452-488`, `subtitles.py:83-164`, `coordinator.py:432-471`,
  `coverage_report.py:62-72`, `integrity.py:170-232`, `quality.py:222-239`, `export.py:187-203`,
  `search_index.py:174-214`, `manifest.py:179-221`,
  `bilibili-asr-archive/src/bili_asr/storage/database.py`.
- Operator surfaces: `bilibili-asr-archive/README.md:391-433` ("Where the artifacts go"),
  `bilibili-asr-archive/docs/artifact-root.md` (validation table, the four tails, the migration section, the
  fsync and cap qualifications), `bilibili-asr-archive/docs/audio-retention-policy.md`.
- Verification: `bilibili-asr-archive/tests/test_artifact_root.py` (precedence, lexical path, identity case, ordered bases),
  `bilibili-asr-archive/tests/test_artifact_root_writes.py` (write base and recorded spelling, retention, per-base reclaim),
  `bilibili-asr-archive/tests/test_artifact_root_readers.py` (same inventory at either root, the legacy caption row, the
  symlinked-ancestor root), `bilibili-asr-archive/tests/test_cli_artifact_root.py` (the four refusals through the real
  `cli.main`, the flag matrix, retention wiring); QA gate `{SDD_DIR}/20260919-artifact-root/review/qa.md`
  recorded 600 passed / 0 failed across 21 files plus the refusal and `--help` probes.
