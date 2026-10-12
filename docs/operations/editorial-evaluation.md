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

## Opt-in provider comparison

The CLI defaults to offline replay. A provider comparison requires
`--allow-paid-calls`, exactly one saved call, and a dedicated private SQLite
`--ledger`. It compares disabled thinking with temperature .2, then enabled
thinking with effort low, retaining the exact historic chunk and system prompt.
These are explicitly new request configurations; they do not update the frozen
source input or production jobs. The two modes change several controls together,
so this comparison is an endpoint smoke check, not an isolated causal estimate
of temperature or effort.

```bash
PYTHONPATH=src python scripts/evaluate_editorial.py \
  --database /path/to/private/archive.db --call-id SAVED_CALL_ID \
  --allow-paid-calls --ledger /path/to/private/experiment.db \
  --endpoint https://opencode.ai/zen/go/v1 --model deepseek-v4.1-flash \
  > /path/to/sanitized-report.json
```

The existing `DeepSeekClient` obtains only the endpoint's API key environment
variable (`DEEPSEEK_API_KEY` or `OPENCODE_API_KEY`). Keys never enter request
evidence. The ledger includes full model requests and responses, including
source prose, so keep it private and outside published artifacts. Standard
output contains only the sanitized report.

Each experiment permits **four physical reservations total**, **two per
variant**, **8192 output tokens per call**, and a **180-second response timeout**.
The output cap includes reasoning tokens. Larger historic chunks may fail with
`finish_reason=length`; report that real failure rather than shrinking the
original sample or weakening validation. A strict cross-paragraph failure alone
allows the second call with the existing canonical feedback policy. Truncation,
HTTP failures and unknown sends are not automatically retried.

SQLite `BEGIN IMMEDIATE` commits the reservation before HTTP, outside the
network transaction. Failed and unfinished sends remain consumed. Restart
reuses completed evidence, never resends an uncertain reservation, and refuses
changed sample/config/budget identity. It checks the canonical manifest body,
table schema, contiguous reservation ordinals, known variants and both call
caps before sending, and refuses a corrupted ledger without resetting it.
Reusing the same ledger preserves the
cap; creating another ledger is a separately authorized experiment. Token
limits bound output volume, not a monetary price: historical input length and
current provider pricing still affect cost.

As checked on 2026-10-12, the official DeepSeek reference documents top-level
`reasoning_effort`, temperature effective only without thinking, and top_p
effective only with thinking in .95–1.0. Disabled thinking fixes effective top_p
to 1. These documented official semantics support the request adapter's shape;
they do not establish OpenCode Go enforcement.
[DeepSeek Chat Completions reference](https://api-docs.deepseek.com/api/create-chat-completion/).

No paid provider calls were performed for this implementation. Accordingly,
OpenCode Go HTTP compatibility, control enforcement and semantic quality remain
unverified. The harness records observed HTTP response acceptance separately
from strict validation and keeps `provider_parameter_enforcement=not_verified`
and `semantic_quality=not_reviewed`. Populate human-reviewed quality ratings
before using any results to change defaults.
