# Editorial recovery evaluation

`scripts/evaluate_editorial.py` replays explicitly selected saved calls with no
network access. It opens the source SQLite database in `mode=ro`, checks the
frozen snapshot digest and exact request chunk/prompt, and runs the existing
`parse_response` and `validate_revision`. No reference, paragraph or response is
modified. A new `deepseek-v2` feedback request is only previewed by its hash.
Historical input identity, request policy and evidence remain intact.
Only original physical provider calls are accepted; replay/local-precheck
records are rejected. Persisted request fingerprints are verified. Historical
calls lacking fingerprints are marked `unavailable_legacy`; their full original
request controls are checked against the frozen config, without inventing a
historical fingerprint.

```bash
PYTHONPATH=src python scripts/evaluate_editorial.py \
  --database /path/to/private/archive.db \
  --call-id SAVED_CALL_ID > /path/to/report.json
```

Select one to five distinct calls. The report includes provenance, request and
response hashes, strict validation diagnostics and actual historical usage;
it excludes transcript prose and full requests/responses. The source database
is a private prerequisite and is not committed to this repository.

## Historical sample replay on 2026-10-12

Three exact saved production failures from the local
`local-upgrade-1791603458/archive-v2-workset` copy reproduced
`cross_paragraph_reference` with the current validator. All snapshot digests
and stored request chunks/prompts passed identity checks. These calls predate
the specific 2026-10-11 incident in #350; they are not that incident's evidence.

| Saved call | Part | Editable segments | Invalid references | Prompt tokens | Completion tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| `94a8efdd979341929aec5fdfc6837280` | 1564 | 499 | 3 | 34655 | 19500 |
| `e139c9b7b2b64f8988b8130a4146f37c` | 163 | 255 | 1 | 47285 | 28565 |
| `003e71a95d6c4d13898704164ed58244` | 117 | 369 | 1 | 47133 | 32344 |

All three inputs retain `legacy-v1` request semantics. Offline replay made zero
physical provider calls; it proves reproducibility and feedback construction,
not improved regeneration success rates or semantic quality. The regression
suite separately verifies that a first successful chunk is called once when a
second chunk fails cross-paragraph validation, regenerates legally, and commits
the complete revision while retaining the failed response.

## Quality and parameter evidence

HTTP acceptance, valid JSON, strict structural acceptance and human-reviewed
semantic quality are separate outcomes. A provider accepting `reasoning_effort`,
`temperature` or `top_p` does not prove that it enforced the setting. Keep
unverified proxy behavior explicit, including after HTTP 200.

Before changing defaults, compare three to five representative parts with the
same base/reference evidence. Record proper-name errors, missed corrections,
meaning changes and unsupported additions with human-reviewed counts, alongside
validation failures, latency and actual token usage. Suggested comparisons are
context 2 versus 4, high versus max for complex terminology, and top_p .95 versus
1.0; change one setting at a time. Structural acceptance cannot supply those
semantic ratings. This replay report supports no production default changes.
