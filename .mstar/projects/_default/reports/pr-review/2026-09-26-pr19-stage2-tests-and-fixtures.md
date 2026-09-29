---
stage: 2
seat: tests-and-fixtures
domain: tests-and-fixtures
pr: 19
head: 84e9767146c03977812591a48a991e0fce7de985
diff_base: 9d530cd646e50142cd92789b2494c72806025ffd
---

# Stage 2 evidence — tests-and-fixtures (PR #19)

## [TEST-01] No test pins DEFAULT_HOTWORDS, so the list can be silently rewritten again

- **Evidence**: `bilibili-asr-archive/src/bili_asr/asr.py:100` (33 entries) vs
  `bilibili-asr-archive/tests/test_asr_qwen.py:503` (the only hotword assertion — env-supplied terms)
- **Impact**: the defect this PR repairs (33→26 silent rewrite, every gate green) is fully repeatable today
- **Effort**: XS · **Risk**: LOW · **Confidence**: HIGH · **Merge class**: should-fix
- **Fix sketch**: assert the exact tuple, or compare it against the README's documented entries

Verified by the main agent: `grep -rn DEFAULT_HOTWORDS tests/*.py` → **0 matches**;
`DEFAULT_HOTWORDS` parses to 33 entries at HEAD.

## [TEST-02] The four new codec tests stub both readers, so an inert fallback stays green

- **Evidence**: `bilibili-asr-archive/tests/test_asr_qwen.py:606`, `:635`, `:651` (stubs); the only real
  decode is `:671` — a `.wav`, the one format that never enters the fallback
- **Impact**: the suite cannot see the must-fix above; the register's own owed item ("every ASR fixture is
  `.wav`") stands unfilled
- **Effort**: M · **Risk**: MED · **Confidence**: HIGH · **Merge class**: should-fix
- **Fix sketch**: generate a short AAC `.m4a` with ffmpeg at test time (skip when absent)

Verified by the main agent: the 4 new tests **pass under librosa 1.0.0**, where the fallback cannot decode.

## [TEST-03] The resample branch the new fallback feeds is executed by zero tests

- **Evidence**: `bilibili-asr-archive/src/bili_asr/asr.py:851-854`; every `transcribe()` fixture returns
  16000 (`bilibili-asr-archive/tests/_asr_fakes.py:172`), and the one 48000 stub (`:621`) stops at
  `_read_audio`'s return value
- **Impact**: the fallback returns the file's native rate (48000 for the corpus), so the branch is on the
  critical path for exactly the new inputs and nothing exercises it
- **Effort**: S · **Risk**: LOW · **Confidence**: HIGH · **Merge class**: should-fix
- **Fix sketch**: add a test whose fake reader yields 48 kHz and assert real-seconds offsets from `transcribe()`

Main-agent trace (`sys.settrace`, ASR suite): `asr.py:404` FALLBACK → **2**; `:409` TRANSPOSE → **2**;
**`:854` RESAMPLE → 0**.

## [TEST-04] A new assertion is tautological

- **Evidence**: `bilibili-asr-archive/tests/test_asr_qwen.py:594` (`def load(self, path, sr=None, mono=False)`)
  vs `:630` (asserts exactly those values); real `librosa.load` defaults are `sr=22050, mono=True`
- **Impact**: the message claims it proves "keeps the native rate and both channels", but it cannot fail
- **Effort**: XS · **Risk**: LOW · **Confidence**: HIGH · **Merge class**: nit
- **Fix sketch**: mirror the real signature in the stub (`sr=22050, mono=True`)

Main-agent verification of real defaults via `inspect.signature(librosa.load)`: `sr=22050`, `mono=True`.
