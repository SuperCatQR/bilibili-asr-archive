# Independent historical review — #66 and #103

Review performed on 2026-10-06 (Asia/Hong_Kong) by the separately delegated
`harness_policy` reviewer, who did not author either historical change. This is
a new review performed now. It does not assert that an independent verdict
existed before either original merge. No GitHub issue, review, or PR was written.

## Exact scope and source retrieval

The local repository lacked the requested historical objects. Read-only GitHub
compare API calls resolved both ranges without substituting the current tree:

| Issue | Exact base | Exact head | Comparison |
| --- | --- | --- | --- |
| #66 | `bda94654ec52014ee5fed4606acde36b04b9c4a5` | `fb09a37a3597b64cc0c940e6967cc5f5514c53d1` | 1 commit, 5 files; every file had a patch |
| #103 | `d42f90334d72566dc9f433c1b8bb3e44cfca54fa` | `40eea782c6bf1064955d2da9bb1f6e9ccf2450d8` | 3 commits, 32 files; every file had a patch |

Sources: [#66 exact comparison](https://github.com/SuperCatQR/bilibili-asr-archive/compare/bda9465...fb09a37),
[#103 exact comparison](https://github.com/SuperCatQR/bilibili-asr-archive/compare/d42f903...40eea78).
The requested #103 range is the completion/fix diff: its base already contains
parts of shape A. This review does not mislabel that range as the entire initial
layout implementation.

Exact head tarballs were retrieved through the GitHub API and only their product
subtrees extracted under ignored `.test-tmp/historical-66` and
`.test-tmp/historical-103`. Python import-origin assertions confirmed that each
run imported that head's own `src/bili_asr/__init__.py`. Neither historical
snapshot was changed. Compare JSON and reproduction scripts remain ignored
local evidence, rather than new tracked copies of historical sources.

## #66 verdict: historical head needed corrections; follow-up fixes exist

Read the three production diffs (`cli.py`, `services/audio_inventory.py`, and
`storage/database.py`) and both test diffs. Checked resolved audio storage keys,
size/hash default and deep reconciliation, writer locking, unreadable/missing
paths, write-error handling, read ordering, duration propagation, and chunked
SQLite lookup bindings. The focused historical run passed **45 tests in
57.16 seconds**:

```sh
PYTHONPATH="$PWD/src" /home/chosenecho/.venvs/bili-asr-pipeline/bin/python -m pytest -q \
  tests/test_audio_inventory.py tests/test_persistence_scale.py
```

**P2 — aborted walk violates its summary/reporting claim.** At `fb09a37`, the
exception branch returns before printing the promised summary. Its count is
`len(repository.read_audio_object_keys())`, the store's total, which cannot
describe how many objects this invocation wrote. The historical test asserted
the stderr failure message but did not require the summary. This is an actual
historical finding, despite all 45 selected tests passing.

The read-only API confirmed follow-up
[`62ed247c07bc35e3d18fcf8123ff7271fb02427f`](https://github.com/SuperCatQR/bilibili-asr-archive/commit/62ed247c07bc35e3d18fcf8123ff7271fb02427f).
The current CLI has the corrective summary, explicitly labels `recorded` as the
store's current total on abortion, and reports unknown per-walk counters as `?`.
The current regression test asserts that summary. No new repair for this
historical finding is necessary here.

Historical content-deduplication is also qualified: the exact head keys known
objects by storage path and lacks the later digest-membership short circuit.
The read-only API confirmed
[`dad656d58335009a6d43937110d59167fd10f896`](https://github.com/SuperCatQR/bilibili-asr-archive/commit/dad656d58335009a6d43937110d59167fd10f896)
and its byte-identical-file oscillation fix. Current source and
`test_byte_identical_files_do_not_oscillate_the_store` retain that correction.
This review does not claim to have rerun the abandoned historical reviewer's
probe or to have independently measured its quoted historical counters.

The review obligation in #66 is now discharged by this explicit verdict and
current follow-up validation. It is not an unconditional approval of `fb09a37`.

## #103 verdict: historical head needed corrections; new current repair included

Read all production/script/document patches and changed test fixtures. Examined
canonical bundle path use, caption publication, proofread output separation,
search-index imports, conservative collision discovery, and quality identity
matching. The exact-head focused run produced **214 passed, 1 failed in
30.81 seconds**, selecting:

```sh
PYTHONPATH="$PWD/src" /home/chosenecho/.venvs/bili-asr-pipeline/bin/python -m pytest -q \
  tests/test_archive_md.py tests/test_artifact_root_writes.py tests/test_manifest.py \
  tests/test_proofread.py tests/test_quality.py tests/test_search.py \
  tests/test_search_index.py tests/test_subtitles.py
```

**P2 — quality accepts another page's bundle.** The exact diff changes
`stem in path.name` to `stem in path.as_posix()`. A row for `BV1demo:p1` accepts
`transcripts/BV1demo.p10/bundle.srt`; it also accepts
`BV1demo.p1/transcripts/BV1other.p0/bundle.srt`. Both independently constructed
files return `reasons=()` and `cue_count=1` through `QualityAnalyzer.analyze` on
the exact historical head and the current pre-fix checkout
`b872c10cdaa7d1d8264b2e316bcd67e628478407`. The same valid `p1` bundle is the
positive control. A page-number prefix and an unrelated ancestor are not an
artifact identity; this allows a corrupted declaration to appear healthy.

This review commit repairs current `quality._check_identity`: fixed canonical
bundle filenames require the immediate parent to equal the exact stem (or its
explicit `.proofread` sibling). Legacy filenames require a bounded stem in the
filename itself. It adds four negative controls covering canonical and legacy
page-prefix/ancestor mismatches, plus four positive controls covering canonical,
proofread, legacy SRT, and composite legacy Markdown names. No reason code or
serialized field is added.

**P2 — historical layout test still asserts removed format directories.**
`test_the_coordinator_archives_with_bundles_at_the_artifact_root` successfully
checks the canonical files, then fails at historical line 227 because it still
requires `transcripts/srt`, `txt`, `md`, and `raw` directories. The current
[`04aa02b`](https://github.com/SuperCatQR/bilibili-asr-archive/commit/04aa02b)
already corrects that assertion to canonical bundle files and absence of those
old directories. The current focused run includes this corrected suite.

The review obligation in #103 is discharged by the explicit historical verdict
and the new repair. Historical `40eea78` remains a head with findings; no
retroactive clean approval is claimed.

## #101 compatibility decision recorded alongside the repair

The two `artifact_missing` additions describe different internal paths: no
declared/derivable candidate, and an explicitly named confined artifact whose
bytes are absent. The public quality surface intentionally aggregates these as
one backlog code. It does **not** add fine-grained attribution, publish declared
paths, alter frozen `to_dict`/CSV fields, or promote absence to a defect.

Source comments now explain the distinction. A fixture executes both branches
and asserts the same complete frozen payload (zero cues/artifacts, one
`artifact_missing`, empty diagnostics). Existing backlog/strict and defect exit
contract tests remain part of current verification. #101 can be resolved as a
documented compatibility decision, not as newly implemented diagnostic detail.

## Current verification and limits

WSL uses existing Python `/home/chosenecho/.venvs/bili-asr-pipeline/bin/python`,
with `PYTHONPATH="$PWD/src"` from each product directory. No engine, package,
GPU model, or external media was installed or downloaded. Historical focused
tests are not historical full-suite claims. No GPU, production-corpus, installed
CLI, or engine-schema acceptance is inferred from them.

Current final regression: **155 passed in 13.98 seconds**:

```sh
PYTHONPATH="$PWD/src" /home/chosenecho/.venvs/bili-asr-pipeline/bin/python -m pytest -q \
  tests/test_quality.py tests/test_quality_raw_confinement.py \
  tests/test_quality_path_probe_cost.py tests/test_proofread.py \
  tests/test_artifact_root_writes.py tests/test_cli_exit_contract.py \
  tests/test_audio_inventory.py
```

This covers quality, confinement/probe cost, proofread, artifact-root publication,
CLI exit semantics, and both historical audio-inventory follow-up fixes. The
four new negative identity controls were also run with the exact historical
`_check_identity` function substituted only in the Python process: all four
failed as expected. The source files were not mutated for that negative-control
run. `git diff --check` also passes.
