# Documentation issue burndown — 2026-10-06

Branch `codex/burndown-docs`, based on `9f7e0c5`. This change corrects current
documentation and retrospective attribution without changing archive, manifest,
ASR or engine behavior. The only Python change is the hotword governance comment.

| Issue | Result and acceptance evidence |
| --- | --- |
| #83 / I-000071 | Projection frontmatter contract now lists ten keys, including the independent video_title from the joined video facts. Checked against archive.write_archive and transcript projection input fields. The metadata contract already lists 25 keys and needed no edit. |
| #164 / I-000162 | Converge compass now attributes delivery to the re-scoped missing_subtitle → meta_ok mapping. It explicitly states that 12 fixture pins and full F7/R13/R15 closure did not land; direction lock preserves the original proposed target but labels it as such. Links point to the original plan STOP clause and I-000156/I-000157 residuals. This does not claim those selection obligations have been implemented. |
| #165 / I-000163 | Compass now records the contemporaneous I-000163 report of approximately 73 failures / five collection errors, distinguishes the eight attributed failures from the whole baseline, and states that original command/output and identities were not recovered. Tracked iteration history has only the compass/direction-lock package; the register is the recoverable historical source, not a fresh measurement. Linked 2026-10-04 report independently records base f537cb5, 2066 passed / 32 failed / 51 skipped / zero setup errors and failure families. That later run is not substituted for the older baseline. |
| #171 / I-000169 | README explains snapshot plus journal replay, last complete row per work item, valid absent snapshot, compaction, and copying both files with writers stopped. derive-manifest writes are described as journal appends with normal compaction instead of snapshot-only appends. Checked against ManifestStore.load/_replay/_maybe_compact. |
| #177 / I-000175 | README now names test_installed_cli.py and test_verify_baseline.py as recursive provisioning exclusions and explicitly retains in-process test_cli_help.py coverage. Checked against verify_baseline staging exclusions. |
| #41 / I-000017 | README and DEFAULT_HOTWORDS comment identify 扬弃 as measured on the 2026-09-18 old-engine A/B and the other five as unverified in benefit. Corrected the inaccurate claim that every term's census had more errors than correct forms. Current Qwen measurement remains a separate requirement and default hotwords remain empty. This resolves wording/attribution only; no GPU or five-term measurement is claimed. |
| #61 / I-000043 | README qualifies historical 150/1730 and 6/1730 figures by their 2026-09-25 report, external/reviewed archive origin and missing host/root/denominator provenance. It requires host, root, date, selector and units with future reports, explicitly declines to use either figure as current checkout coverage, and states no external archive was copied or live measurement repeated. This records the issue's deferred evidence limitation honestly. |
| #114 / I-000106 | README describes stored-caption publication versus the ASR stage publishing its own audio-branch bundles. It explains a zero-candidate successful publish-transcripts call on an audio-only root without caption candidates does not attest ASR completion. Root lane owns the requested audio-only regression fixture; this lane contributes the documentation half of acceptance. |

## Verification

WSL existing Python 3.12 environment, from this worktree's product cwd:

```sh
cd /mnt/c/wt/bd-d/bilibili-asr-archive
PYTHONPATH="$PWD/src" /home/chosenecho/.venvs/bili-asr-pipeline/bin/python -m pytest -q \
  tests/test_transcript_projection.py tests/test_manifest.py \
  tests/test_verify_baseline.py tests/test_cli_help.py
```

**140 passed in 18.82s.** These exercise real projection/manifest behavior and
baseline staging/CLI contracts corresponding to the corrected descriptions.
`git diff --check` passed. Newly added local document links were checked to exist.
No new tests mirror prose or comments.

No live Bilibili request, model invocation, GPU run, historical archive
reconstruction, package installation or harness-engine state mutation was done.
Engine issues #127/#192/#207 and historical independent reviews #66/#103 belong
to the root lane. The complete prior read-only matrix remains ignored at the
primary product `.test-tmp/audit-harness.md`; it is not a tracked acceptance
report and did not modify GitHub issue state.

Ready for documentation closure: #83, #164, #165, #171, #177. #41 and #61 can be
closed as explicit attribution/deferred-evidence decisions if the maintainer
accepts that scope; their unavailable external measurements are still disclosed.
#114 is ready only after the root lane's audio-only expectation regression passes.
