# Seat B — tests and fixtures (adversarial, mutation-based)

Reviewed the pinned head `b43234b`. Method: mutate product code in the disposable
`/mnt/e/r5-scratch`, run the named node, restore (md5-verified). Read-only in the repository.

## Findings, each re-verified by the driving session

### B1 — must-fix: the primary read lost its only real round-trip (CONFIRMED)
Deleting `test_the_two_readers_agree_on_a_real_wav` removed the last test that performs a real,
unmocked primary `_read_audio` of a real file. The surviving primary-value check
(`test_a_decodable_file_never_reaches_the_fallback`) monkeypatches `sf.read` with `lambda *a, **k:`,
so it swallows every read option and cannot see any of them change.

Driving-session verification (mutating the primary read in `asr.py`, then running the suite):

| mutation of the primary read | result |
|---|---|
| `sf.read(path, dtype="float32", frames=1000)` — silent truncation | **46 passed** |
| `sf.read(path, dtype="int16")` — wrong dtype | **46 passed** |

Both should fail. Restored afterwards; suite green again. The deleted test is recoverable from
`git show 1f2dcd0:bilibili-asr-archive/tests/test_asr_qwen.py` and only needs the librosa half
dropped, since it was there to compare two readers and now there is one reader for WAV.

### B2 — should-fix: the argv assertion is order-blind (CONFIRMED)
`assert ("-rf64", "auto") in pairs` is set membership, so a later override passes. Verified
independently on ffmpeg 6.1.1: `-rf64` is **last-wins** (`auto` then `never` produced a **RIFF**
container; `never` then `always` produced **RF64**). A mutated argv `-rf64 auto … -rf64 never`
left the test **passing** — the exact scenario the test exists to prevent, shipping green.

Fix: assert exactly one `-rf64 auto`, positioned **after** `-i`, and no later `-rf64` (or `-f`)
override.

### B3 — should-fix: skipping contradicts this repository's own stated policy (CONFIRMED)
With a `PATH` lacking `ffmpeg`, the suite reports `43 passed, 3 skipped` and **exit 0**; the three
skips are precisely the real-decode tests. That is what this repo's own harness forbids —
`tests/installed_cli.py`'s docstring reads: *"Missing-install policy: fail the test (never
pytest.skip / xfail) with a named prerequisite. Automated verification must not go green because a
console script was absent."*

`ffmpeg` is a **declared product requirement** (`AGENTS.md`, and `pyproject.toml`'s NOTE), which is
exactly the "console script absent" case that policy covers. So the fix is the repo's own rule:
fail with a named prerequisite rather than skip.

(Tension worth recording: the driving session's F3 independently found the same skip behaviour but
judged it *correct*, on the reasoning that a suite must not fail where the binary is legitimately
absent. Seat B's point is stronger: the repository has already decided this question in the
opposite direction for the same class of dependency, and consistency with that decision beats a
locally reasonable preference. The policy wins; F3 is superseded.)

### B4 — should-fix: `AudioDecodeError` has zero coverage (CONFIRMED)
Two mutations, both leaving **46 passed**: replacing its `raise` with a bare `RuntimeError`, and
deleting the entire non-zero-exit guard (784 characters). The class docstring claims its name is
what an operator sees in the run ledger, and nothing pins that. One test asserting
`pytest.raises(asr.AudioDecodeError)` on a non-audio input closes it.

### B5 — should-fix: the torch stand-in is missing what the loader reads (CONFIRMED, latent)
The product reads `torch.bfloat16` (`asr.py:773,777`) and `torch.cuda.is_available` (`:837`); the
stub provides `cuda`, `inference_mode`, `no_grad`, `Tensor` — not `bfloat16`. Verified that the
stub raises `AttributeError` on `.bfloat16`. No current test reaches it (all fake the model
factory), so this is a trap for the next test that touches the real loader, not an active failure.

### B6–B8 — nits
* `test_a_fallback_read_still_produces_the_same_cues_as_a_primary_read` survived seven of eight
  mutations and died only on an *empty* fallback array — a property test A already covers. Not
  vacuous, but close; the docstring is honest about the aligner while the name is not.
* The acronym pin passes `item` / `XXITEMXX` (case and substring variants); exact-token absence is
  the real property, so the name over-promises slightly.
* An unrelated pre-existing failure in the not-in-repo baseline (`1 failed, 1709 passed`), from a
  fixture copying a missing `python` path under the scratch tree.

## Verified sound
* The AAC fixture is byte-identical across 5 encodes (`md5 33aed95d…`) and uses ffmpeg's bundled
  `aac` encoder, so there is no libfdk or rate-negotiation dependence; thresholds have wide margins
  (peak 0.092 against a `>0.01` bar).
* Test A kills 5/5 mutations (transpose, wrong rate, `-ar 8000`, zeroed samples, `-ac 1`); the
  resample test 5/5; the dependency test 3/3; the never-reaches-fallback test 5/5; all three
  hotword pins kill.
* The `-nostdin` / `stdin=DEVNULL` redundancy behaves exactly as its docstring documents —
  independently sufficient, jointly required, matching the driving session's own measurement.
* Per-node `importorskip` for `numpy`/`soundfile`/`soxr`, so no whole-file vanishing.

## Review hygiene note (raised by the seat, owned by the driving session)
The seat observed `.mstar/knowledge/testing-patterns/hotword-list-measurement.md` changing mid-review
and correctly declined to attribute it to itself. **It was the driving session**: a citation this
branch had introduced was found to point at `asr.py:316` when the code it describes is at `:351`,
and it was corrected once the seats were already reading. The tree therefore moved under the seats.
Impact is bounded — the change is one line inside a Markdown doc, in a file no seat was asked to
review and no test reads — but it is a process fault and is recorded rather than smoothed over.
