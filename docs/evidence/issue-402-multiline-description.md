Issue #402: Bilibili multiline descriptions
==========================================

The list/detail adapter and both metadata DTOs accept description prose using
the same bound as frozen source metadata: at most 65,536 characters, including
CR/LF/tab, while NUL, other controls and Unicode surrogates remain invalid.
Cover URLs and scalar names keep their existing validation.

The regression drives the real gateway seam, ingestor and SQLite repository,
then reads both scalar and batch frozen-source candidates and round-trips the
source codec. It preserves multilingual text, CR/LF/tab and normal sibling
fields. Existing whitespace-only values keep their documented projection;
the raw-observation follow-up preserves the original platform value separately.

Validation on Windows/Python 3.12: gateway, ingest, repository and refresh suites.
The deliberate mutation reinstates dropping multiline descriptions and must
fail the persistent-source regression before the correct implementation is restored.
