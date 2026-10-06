"""Local ASR boundary — Qwen3-ASR on transformers, with the forced aligner for timings.

The engine is a **hard switch** (plan `20260924-qwen3-asr-transformers`, D2): there is no FunASR
code path and no runtime engine flag.  Rollback is a revert of the commit that lands this file,
not a switch.

Why the boundary looks like this — measured on the archive's own audio (plan §13.5):

* the decoder returns **text only** (``language <LANG><asr_text>…``), never timings;
* timings come from a second model, ``Qwen3-ForcedAligner-0.6B``, a non-autoregressive token
  classifier whose single forward pass over (audio <= 180 s, that text) returns **per-character**
  ``{text, start_time, end_time}`` for Chinese;
* a per-cue confidence does not exist in this engine, so no confidence key is published (plan D4) —
  the frontmatter writer already omits those keys when no score is present;
* the decoder costs ~0.41x real-time while alignment costs ~0.1 s per 60 s chunk, so the chunk size
  is tuned around the decoder, not the aligner.

So: audio is chunked (the aligner's practical bound is 180 s), each chunk is transcribed and then
aligned, the per-chunk timings are offset and stitched, and the surviving cue rules — unchanged from
the FunASR era, they were measured on this corpus — group the aligned units into subtitle lines.

Dependencies: ``transformers>=5.13`` (native Qwen3-ASR support), ``torch``, ``accelerate`` (the
``device_map`` path), ``soundfile``/``soxr`` (reading and resampling audio), and the **``ffmpeg``
binary** — the decoder for the containers ``libsndfile`` cannot open (see :func:`_read_audio`).
``ffmpeg`` is a declared requirement of the product, not an optional extra: the download layer
already shells out to it to remux explicit FLAC streams.  Transformers is imported only when a
runner first transcribes; no model download orchestration lives here.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Iterable, NamedTuple

DEFAULT_MODEL = "Qwen/Qwen3-ASR-1.7B-hf"
DEFAULT_ALIGNER_MODEL = "Qwen/Qwen3-ForcedAligner-0.6B-hf"
DEFAULT_TRANSCRIPT_LANGUAGE = "und"

_INSTALL_HINT = 'pip install -e "bilibili-asr-archive/[asr]"'


def provenance_language(provenance: Any) -> str:
    """Return the persisted language with one shared implicit fallback."""
    if isinstance(provenance, Mapping):
        value = provenance.get("language")
        if value:
            return str(value)
    return DEFAULT_TRANSCRIPT_LANGUAGE

#: Transformer output can leak its own control markers when a caller decodes without
#: ``skip_special_tokens``; nothing downstream may see one.
_RICH_TAG = re.compile(r"<\|[^|>]+\|>")

# ---------------------------------------------------------------------------------------
# Chunking.  The aligner documents up to 5 minutes; the reference implementation uses 180 s
# when timings are wanted, which is always here.  A chunk boundary is placed at the quietest
# point in a window around the target so it does not slice a word, and the chunks tile the
# input exactly: no overlap, no gap, no dropped tail.
# ---------------------------------------------------------------------------------------

DEFAULT_CHUNK_SECONDS = 180.0
_CHUNK_SEARCH_EXPAND_S = 5.0
_CHUNK_MIN_WINDOW_MS = 100.0
_CHUNK_MIN_SECONDS = 0.5
SAMPLE_RATE = 16_000

# ---------------------------------------------------------------------------------------
# Coverage attestation (plan asr-coverage-attestation; iteration D9 measurement, D11 carrier).
#
# A run can decode a recording in full and still come back with a transcript that covers only
# part of it — measured on `BV1YFEUzpEsT:p0` (I-000188): the decode was 73.561 s (3 244 032
# samples @ 44.1 kHz, resampled to 16 kHz) and the archived cues spanned 0.0–59.0 s, i.e.
# `produced_s / decoded_s = 59.0 / 73.561 = 0.80204…`, while the row recorded `outcome=stored`,
# a complete bundle and no warning.  Nothing compared the span the model produced with the audio
# it was fed; this block is that comparison, and it is the only thing that measures it.
#
# Threshold basis: the defect sits at 0.80204 and a correct run sits just under 1.0, so the
# constant lies in (0.803, 1.0).  0.97 is biased high on purpose — a false shortfall flag on a
# real success costs more than a narrow band, because a correct run still loses the sub-second
# edges (VAD lead-in, trailing silence, cue-end rounding), while any loss past ~3% is flagged,
# including a truncated final chunk that a round 0.9 would sail past.  1.0 is rejected:
# harmless arithmetical tails would flag.  Retune from 0.80204, not from a guess.
#
# Detection only: nothing here aborts a run, and nothing suppresses the write.  The transcript is
# the expensive artifact and a partial one is still evidence.
# ---------------------------------------------------------------------------------------

COVERAGE_MIN = 0.97

#: The row keys the measurement writes.  Kept as one tuple so a re-run can clear exactly what a
#: previous run wrote before the new measurement (or the absence of one) is recorded.
COVERAGE_KEYS = ("decoded_s", "produced_s", "coverage", "coverage_min", "coverage_short")

#: Verdicts for a record read back from the archive.  A record with no ``coverage`` is **not
#: evaluable** — never "covered": the archive persists no decoded duration for rows written before
#: this measurement existed, and container ``duration_s`` is a header, not the span the model
#: consumed.  The three values are the whole read-only vocabulary (D9 reading rule).
COVERAGE_VERDICT_COVERED = "covered"
COVERAGE_VERDICT_SHORT = "short"
COVERAGE_VERDICT_NOT_EVALUABLE = "not-evaluable"

#: Generation budget per chunk, in tokens per second of audio.  Chinese speech in this corpus runs
#: near 4 characters/s and one character is about one token, so this is deliberately generous; the
#: full-item measurement (plan §13.5, follow-up) confirms the margin.
_MAX_NEW_TOKENS_PER_AUDIO_SECOND = 8
_MIN_NEW_TOKENS = 256

# ---------------------------------------------------------------------------------------
# Cue rules — SURVIVORS.  Measured on this corpus in the FunASR era; they are product
# decisions (what makes a readable subtitle line), not engine decisions.  Only their input
# changed: per-character alignment units instead of FunASR's token stream.
# ---------------------------------------------------------------------------------------

_SENTENCE_ENDINGS = "。！？!?"
_CUE_MAX_CHARS = 60
_CUE_MAX_GAP_SECONDS = 1.0
_CUE_MIN_CHARS = 6
_CUE_MIN_SECONDS = 1.0
_CUE_CLOSING_MARKS = "。！？!?，、；：,;:"

#: Bounded retry of a failed model load (inherited contract).
MAX_MODEL_LOAD_ATTEMPTS = 3

# ---------------------------------------------------------------------------------------
# Environment knobs.
# ---------------------------------------------------------------------------------------

ASR_MODEL_ENV_VAR = "BILI_ASR_MODEL"
ASR_ALIGNER_ENV_VAR = "BILI_ASR_ALIGNER_MODEL"
ASR_MODEL_REVISION_ENV_VAR = "BILI_ASR_MODEL_REVISION"
#: The operator's *declaration* of the hub-level identity behind the loaded ASR checkpoint.  Read for
#: provenance only — it never reaches the loader — and a blank value means "not declared".
ASR_MODEL_ID_ENV_VAR = "BILI_ASR_MODEL_ID"
ASR_DEVICE_ENV_VAR = "BILI_ASR_DEVICE"
ASR_LANGUAGE_ENV_VAR = "BILI_ASR_LANGUAGE"
ASR_HOTWORDS_ENV_VAR = "BILI_ASR_HOTWORDS"
ASR_CHUNK_SECONDS_ENV_VAR = "BILI_ASR_CHUNK_SECONDS"

#: The shipped decoder-prompt vocabulary.  Governance ruling 2026-09-28 (plan
#: ``20260928-hotword-injection-governance``, residual ``20260922-proofread-wave R1``):
#: **empty while the per-token keep/drop measurement is pending operator re-run.**
#: No token may enter the prompt by speculation — every admitted token has to
#: occur in the run's own first-pass transcript or its paired AI-subtitle text
#: (:func:`evidence_guard_hotwords`), and dropped tokens are recorded in the run
#: ledger as ``hotword_dropped_no_evidence``.  The 33 measured-candidate tokens
#: that populated this list before the ruling — 27 archive terms plus the six
#: homophone entries 扬弃/自在/变易/此在/感性/实存, whose benefit was never verified
#: — are the ruling table's subjects; the archived reasoning for each block is
#: preserved in git history and in ``.mstar/knowledge/testing-patterns/
#: hotword-list-measurement.md``.  When the measurement lands, the kept tokens
#: return here and the rest are dropped from the default source entirely.
DEFAULT_HOTWORDS: tuple[str, ...] = ()

#: The measured-candidate vocabulary — the tokens the 2026-09-28 keep/drop ruling
#: (plan ``20260928-hotword-injection-governance``) measures, with the reasoning
#: each block earned.  These are NOT the shipped prompt list: ``DEFAULT_HOTWORDS``
#: is empty while the ruling is pending operator re-run (no speculative seeding).
#: An operator run may feed these through ``BILI_ASR_HOTWORDS`` or an explicit
#: config, and the evidence guard (:func:`evidence_guard_hotwords`) admits back
#: only the ones the run's own transcript or paired subtitles carry.  When the
#: measurement lands, the kept tokens return to ``DEFAULT_HOTWORDS`` and the rest
#: are dropped from this list too.
MEASURED_HOTWORD_CANDIDATES: tuple[str, ...] = (
    "未明子", "主义主义", "拟态论", "国际劳工仲裁", "国际劳联", "马恩牌", "攻势", "智利",
    "根正苗红", "亚美利坚", "黑格尔", "海德格尔", "拉康", "齐泽克", "德勒兹", "康德",
    "观念论", "本体论", "现象学", "辩证法", "定在", "自为", "理念性",
    # The homophone class, added 2026-09-17 from the season run's own output
    # (workflow ``e2e-23191782-season-7686105``: 14 lectures, 25.2 h, 18 287
    # cues).  Each entry below is a term the model got *wrong* far more often
    # than right, and every one of them is the *exact homophone* of a common
    # word — which is why the decoder's prior wins and why the prompt is the
    # right lever here:
    #
    #   扬弃 (sublation)  10 correct vs 89 wrong (阳气 62, 洋气 27)  90 %
    #   自在 (in-itself)  40 vs 13 (子在)                            25 %
    #   变易 (becoming)    0 vs  7 (变异)                           100 %
    #   此在 (Dasein)      4 vs  3 (次在, 词在)                      43 %
    #   感性 (sensibility)12 vs  3 (感兴)                            20 %
    #   实存 (existence)  17 vs  3 (时存)                            15 %
    #
    # 扬弃 is the reason this block exists: it is the central operation of
    # Hegel's *Logic*, and these lectures read that book aloud, so the term is
    # spoken constantly — yet the decoder preferred the common word 阳气 nine
    # times out of ten (worst item: 《逻辑学》第二讲, 4 correct vs 57 wrong).
    # The control that makes this an argument rather than a hunch: the entries
    # already in this list that are equally homophone-prone are *error-free* on
    # the same audio (定在 145/0, 自为 34/0, 理念性 69/0).
    #
    # Evidence status, stated plainly, as for the Latin block below: the errors
    # above are measured, the *benefit* of these six is UNVERIFIED until the
    # same audio is re-transcribed.  A confidence-based fix was ruled out first
    # — the 78 mis-rendered cues score a median 0.776 against 0.812 for the
    # corpus, and only 1 of 78 falls at or below ``LOW_CONFIDENCE``, so the
    # model is confidently wrong and ``asr_low_confidence_at`` cannot find this
    # class.  Re-running one affected lecture with and without these entries is
    # the confirming measurement; like the Latin block's, that verification is
    # registered as an open residual rather than claimed here.
    "扬弃",
    "自在",
    "变易",
    "此在",
    "感性",
    "实存",
    # Latin-script terms the corpus actually speaks.  The Chinese-language model
    # fragments these into shards when they are missing from the prompt (measured
    # 2026-09-14 on the ten-video run: "International Employment Matters Tribunal"
    # came out as tryBUNAL / FOR EMP LOYMENT MAT TERS, and the ITEM/AITEM pair as
    # TEM / AITM / ITM).  The spelled-out phrase is listed together with its three
    # component words, so the decoder has the full form and each part of it.
    #
    # The bare acronyms ITEM and AITEM were **removed on 2026-09-17** after the
    # season run measured them doing harm of the kind they were added to prevent:
    # nine occurrences across the 14 archived lectures, e.g. "THE ITEMthat's the
    # question is anITEM ONE", "This is expressed in the finite on the AITEM",
    # "In accessible AITEM distance outside", "就是WHAT IS POSITIVE ITEM" — and
    # every one of them is the acronym capturing a neighbouring word rather than
    # a spoken initialism.  The spelled-out phrase stayed: it appears three times
    # and is genuine each time.  They are therefore deliberately **absent** from
    # this list, not overlooked — re-adding either needs its own measurement.
    #
    # Evidence status: the surface-form measurements are the **retired FunASR-Nano**
    # checkpoint's and do not carry over unmeasured; re-measuring this list under the
    # engine that ships, with insertions counted separately from recoveries, is T5.
    # That round ran 2026-09-26 on the frozen six-item corpus and returned PARTIAL:
    # every exercised term came out identical with and without the prompt (R=0, I=0),
    # and E=7 left the recovery clauses uninformative — so the list's benefit is still
    # unmeasured, and the absence of a falsifying result is not evidence of benefit.
    # Record: `iter-2026-09-qwen3-asr-closeout/guides/t5-hotword-measurement-results.md`.
    #
    # Two facts from the original block were dropped when this list was restored in
    # 83ba8d0 and are restored here, because nothing else in the repository carries
    # them.  (1) The harm measurement that justified the removal was taken on
    # `BV19hG56hEfV.p2`, which carries 5 of the 9 bad cues.  (2) The *benefit* side —
    # why these acronyms were ever added — was measured on `BV1eGJ46mEHQ`, and **that**
    # video is the one whose audio no longer exists, so the benefit cannot be re-measured
    # from here and must be taken from the counts above.  The asymmetry is the point:
    # the harm can be re-checked (that lecture's audio is one re-download away), the
    # benefit cannot.  Record: `plans/20260917-hotword-acronym-precision.md`, findings
    # D1 and D3.
    "International Employment Matters Tribunal",
    "International",
    "Employment",
    "Tribunal",
)

# ---------------------------------------------------------------------------------------
# Redaction guards.  Engine-agnostic; ``quality.py`` imports ``_FORBIDDEN_PROVENANCE``.
# ---------------------------------------------------------------------------------------

_FORBIDDEN_CREDENTIAL_MARKER = (
    r"(?:^|[^A-Za-z])(?:sessdata|cookie|token|password|secret|credential)(?![A-Za-z])"
)
_FORBIDDEN_VALUE = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://|\\\\|(?:^|[\\/])\\/|(?:^|[^A-Za-z])[A-Za-z]:[\\/]|"
    + _FORBIDDEN_CREDENTIAL_MARKER
    + r")",
    re.IGNORECASE,
)
_FORBIDDEN_LOCAL_SOURCE = _FORBIDDEN_VALUE
_FORBIDDEN_PROVENANCE = _FORBIDDEN_VALUE
_MODEL_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")
_DESCRIPTOR_PATH = re.compile(r"^/(?:proc/(?:self|\d+)/fd|dev/fd)/\d+$")


class ASRDependencyError(RuntimeError):
    """The optional ASR dependency (transformers/torch) is missing or unusable."""


class ASRModelError(RuntimeError):
    """The configured checkpoint could not be loaded, or the run could not transcribe."""


class AudioDecodeError(RuntimeError):
    """The audio file exists but the decoder refused it.

    Distinct from :class:`ASRDependencyError`: the dependencies are present, the *file* is the
    problem (unreadable, or a codec ``ffmpeg`` was not built with).  The coordinator records the
    exception's type name when it has no scalar ``code`` attribute, so this class name is what an
    operator sees in the run ledger.

    What this class does **not** cover, stated because the difference matters for an archive whose
    download stage can be interrupted: a file truncated in the middle decodes **silently short**
    rather than raising.  Measured on a faststart ``.m4a`` cut to 90/70/50/30 % of its bytes, which
    is the shape an interrupted download leaves when ``moov`` precedes ``mdat``: the decode returned
    53.9/41.6/29.4/17.1 s of a 60 s recording, exit status 0, no stderr.  Nothing here compares the
    decoded duration with the row's ``duration_s``, so a short read is not detected — the same was
    true of the ``librosa`` path this replaced, so this is a pre-existing limit rather than a
    regression, but the reader should not infer from this class that truncation is caught.
    """


def _is_redaction_safe_model_identifier(value: str, *, hub_level: bool = False) -> bool:
    """The redaction rule for model identifiers, in one place.

    An identifier-shaped value with no forbidden marker is safe to serialize — that is the rule
    ``provenance()`` has always applied to ``model_name``.  ``hub_level`` additionally demands a
    slash-qualified ``owner/name`` shape, which is what a *declared* producer identity must look like.

    Note what this rule deliberately does **not** redact: a relative checkpoint path such as
    ``models/Qwen3-ASR-1.7B-hf`` passes through, because that is the documented form of a local
    checkpoint (``README.md``) and provenance is supposed to name it.
    """

    if not isinstance(value, str) or not value.strip():
        return False
    if _MODEL_IDENTIFIER.fullmatch(value) is None:
        return False
    if _FORBIDDEN_PROVENANCE.search(value) is not None:
        return False
    return not hub_level or "/" in value


def _is_hub_level_model_name(value: str) -> bool:
    """Whether ``value`` names a hub repository rather than a local path.

    The shape alone cannot tell ``models/Qwen3-ASR-1.7B-hf`` from ``Qwen/Qwen3-ASR-1.7B-hf`` — both
    are two segments once — and the contradiction check must not punish the relative-path form the
    README documents.  Existence answers it on the machine that owns the layout: the checkpoint the
    operator points the knob at is a directory that is *there*, and a hub id is a name that is not.
    The probe resolves against the process working directory, exactly as the loader would.
    """

    if not _is_redaction_safe_model_identifier(value, hub_level=True):
        return False
    return not os.path.isdir(value)


# ---------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ASRConfig:
    """Deterministic, redaction-safe configuration for one ASR run.

    ``language`` is the operator's declaration of what is spoken, passed to both models; ``None``
    leaves the model's own detection in place, and the detected value is deliberately **not**
    archived or published (plan §10 — the archive records what the operator declared, not a guess).

    ``hotwords`` biases the decoder through the processor's free-form ``prompt``; an empty tuple
    sends no bias, and the terms are recorded in provenance.  Governance ruling 2026-09-28:
    speculative seeding is off, so the shipped default is empty and every token that does reach
    the prompt is admitted by :func:`evidence_guard_hotwords` against the run's own evidence
    (the runner's per-run state, not this config — see :class:`ASRRunner`).

    ``model_name`` / ``aligner_name`` are hub ids or local checkpoint directories.  ``model_id`` is the
    operator's declaration of the hub-level identity behind the ASR checkpoint.
    """

    model_name: str
    aligner_name: str = DEFAULT_ALIGNER_MODEL
    model_revision: str | None = None
    device: str = "cuda"
    language: str | None = None
    # 2026-09-28 governance ruling (plan 20260928-hotword-injection-governance,
    # residual 20260922-proofread-wave R1): speculative seeding is off.  No term
    # enters the decoder prompt unless evidence-based seeding admits it (see
    # ``evidence_guard_hotwords``); the shipped default is therefore empty and
    # ``BILI_ASR_HOTWORDS`` supplies operator-declared terms that pass the same
    # guard at run time.
    hotwords: tuple[str, ...] = DEFAULT_HOTWORDS
    chunk_seconds: float = DEFAULT_CHUNK_SECONDS
    offline: bool = True
    local_source: str = "configured-local"
    model_id: str | None = None

    def __post_init__(self) -> None:
        for name, value in (("model_name", self.model_name), ("aligner_name", self.aligner_name)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.model_revision is not None and (
            not isinstance(self.model_revision, str) or not self.model_revision.strip()
        ):
            raise ValueError("model_revision must be a non-empty string or null")
        if not isinstance(self.device, str) or not self.device.strip():
            raise ValueError("device must be a non-empty string")
        if self.language is not None and (
            not isinstance(self.language, str) or not self.language.strip()
        ):
            raise ValueError("language must be a non-empty string or null")
        if isinstance(self.chunk_seconds, bool) or not isinstance(self.chunk_seconds, (int, float)):
            raise ValueError("chunk_seconds must be a positive number")
        if self.chunk_seconds <= 0:
            raise ValueError("chunk_seconds must be a positive number")
        if not isinstance(self.hotwords, tuple) or any(
            not isinstance(term, str) or not term.strip() for term in self.hotwords
        ):
            raise ValueError("hotwords must be a tuple of non-empty strings")
        if not isinstance(self.offline, bool):
            raise ValueError("offline must be a bool")
        if not isinstance(self.local_source, str) or not self.local_source.strip():
            raise ValueError("local_source must be a non-empty identifier")
        if _FORBIDDEN_LOCAL_SOURCE.search(self.local_source):
            raise ValueError("local_source must be an opaque local identifier")
        if self.model_id is not None:
            if not isinstance(self.model_id, str) or not self.model_id.strip():
                raise ValueError(f"{ASR_MODEL_ID_ENV_VAR} must be a hub-level model identifier")
            if not _is_redaction_safe_model_identifier(self.model_id, hub_level=True):
                raise ValueError(f"{ASR_MODEL_ID_ENV_VAR} must be a hub-level model identifier")
            if _is_hub_level_model_name(self.model_name) and self.model_name != self.model_id:
                raise ValueError(
                    f"{ASR_MODEL_ID_ENV_VAR} contradicts {ASR_MODEL_ENV_VAR}: "
                    f"declared {self.model_id!r}, loaded {self.model_name!r}"
                )


def _resolve_chunk_seconds(environment_value: str | None) -> float:
    """Configured chunk cap in seconds; unset keeps the measured default, blank stays unset."""

    if environment_value is None or not environment_value.strip():
        return DEFAULT_CHUNK_SECONDS
    try:
        value = float(environment_value.strip().rstrip("sS"))
    except ValueError:
        raise ValueError(
            f"{ASR_CHUNK_SECONDS_ENV_VAR} must be a positive number of seconds"
        ) from None
    if value <= 0:
        raise ValueError(f"{ASR_CHUNK_SECONDS_ENV_VAR} must be a positive number of seconds")
    return value


def _extra_hotwords(environment_value: str | None) -> tuple[str, ...]:
    """The operator's extra hotwords, in order, without duplicates."""

    if not environment_value:
        return ()
    terms: list[str] = []
    for raw in environment_value.replace("，", ",").split(","):
        term = raw.strip()
        if term and term not in terms and term not in DEFAULT_HOTWORDS:
            terms.append(term)
    return tuple(terms)


def evidence_guard_hotwords(
    candidates: Iterable[str],
    evidence_texts: Iterable[str | None],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Evidence-based hotword guard (2026-09-28 governance ruling, plan
    ``20260928-hotword-injection-governance``).

    A candidate term may reach the decoder prompt only if it occurs in at least
    one of ``evidence_texts`` — the run's own first-pass transcript or the
    paired AI-subtitle text.  Speculative seeding is the insertion-error source
    recorded as residual ``20260922-proofread-wave R1`` (hotword tokens observed
    in output where the audio says something else), so the default path seeds
    nothing: ``DEFAULT_HOTWORDS`` is empty while the per-token keep/drop
    measurement is pending, and operator-declared ``BILI_ASR_HOTWORDS`` terms
    pass through this same guard before they can bias a decode.

    The guard is pure string containment — no model calls, no tokenization.
    CJK terms are matched as-is (a hotword list entry is already the smallest
    meaningful unit, and the corpus text carries no word boundaries to consult);
    Latin-script terms are matched case-insensitively, because the prompt list
    capitalizes them while transcripts do not.  A term occurring only inside a
    longer word *is* matched — that is the deliberate semantics: a term that
    appears anywhere in the evidence is a term this run plausibly needs.

    Returns ``(admitted, dropped)`` in candidate order, de-duplicated.
    """


    def _norm(text: str) -> str:
        return text.casefold()

    seen: set[str] = set()
    ordered: list[str] = []
    for term in candidates:
        term = term.strip()
        if term and term not in seen:
            seen.add(term)
            ordered.append(term)
    folded = [_norm(text) for text in evidence_texts if text]
    admitted = tuple(
        term for term in ordered
        if any(_norm(term) in text for text in folded)
    )
    dropped = tuple(term for term in ordered if term not in admitted)
    return admitted, dropped


def filter_hotwords(
    candidates: Iterable[str],
    *,
    evidence_text: str | None,
    paired_subtitle_text: str | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The two-text call shape of :func:`evidence_guard_hotwords`.

    ``evidence_text`` is the run's own first-pass transcript; ``paired_subtitle_text``
    is the AI-subtitle text harvested for the same part (``None`` when the part has no
    subtitle route).  Both are evidence; a token passing either reaches the prompt.
    """


    return evidence_guard_hotwords(candidates, (evidence_text, paired_subtitle_text))


def default_config() -> ASRConfig:
    """Build the runner configuration from the documented environment knobs.

    ``BILI_ASR_MODEL`` and ``BILI_ASR_ALIGNER_MODEL`` carry hub ids or **local checkpoint
    directories**; the archive's own checkpoints live under ``bilibili-asr-archive/models/`` so a
    run never touches the network.  ``BILI_ASR_MODEL_ID`` is the operator's declaration of the
    hub-level identity behind the ASR checkpoint: read for provenance only, and refused when it
    contradicts a hub-level ``BILI_ASR_MODEL``.
    """

    return ASRConfig(
        model_name=os.environ.get(ASR_MODEL_ENV_VAR) or DEFAULT_MODEL,
        aligner_name=os.environ.get(ASR_ALIGNER_ENV_VAR) or DEFAULT_ALIGNER_MODEL,
        model_revision=os.environ.get(ASR_MODEL_REVISION_ENV_VAR) or None,
        device=os.environ.get(ASR_DEVICE_ENV_VAR) or "cuda",
        language=os.environ.get(ASR_LANGUAGE_ENV_VAR) or None,
        hotwords=DEFAULT_HOTWORDS + _extra_hotwords(os.environ.get(ASR_HOTWORDS_ENV_VAR)),
        chunk_seconds=_resolve_chunk_seconds(os.environ.get(ASR_CHUNK_SECONDS_ENV_VAR)),
        model_id=(os.environ.get(ASR_MODEL_ID_ENV_VAR) or "").strip() or None,
    )


def _materialize_input(audio_path: str) -> tuple[str, str | None]:
    """Return an input path the audio reader can open.

    The CLI hands this boundary a confined descriptor path so the audio never leaves the archive
    root.  Descriptor paths are not universally openable by the decoder libraries, so one is copied
    to a temporary file which the caller removes.  A plain path is returned untouched.

    The original reason (plan §13.1) was a child ``ffmpeg``, which a descriptor cannot be handed to,
    and that reason is live again: ``_decode_with_ffmpeg`` runs ``ffmpeg`` as a child for every
    container libsndfile cannot open, i.e. for every ``.m4a`` this archive downloads.  The descriptor
    is not passed through (``subprocess.run`` is called without ``pass_fds``), so a ``/proc/self/fd``
    path handed to it would resolve inside the child to a closed descriptor — measured: the fallback
    raises ``AudioDecodeError`` for such a path.  This step is therefore load-bearing for the
    project's primary input format, not merely a legacy convenience, and a ``.m4a`` run exercises it.
    """

    if not isinstance(audio_path, str) or not _DESCRIPTOR_PATH.match(audio_path):
        return audio_path, None
    handle, temporary = tempfile.mkstemp(prefix="bili-asr-asr-", suffix=".audio")
    try:
        with os.fdopen(handle, "wb") as target, open(audio_path, "rb") as source:
            shutil.copyfileobj(source, target)
    except OSError:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return temporary, temporary


def _decode_with_ffmpeg(path: str) -> tuple[Any, int]:
    """Decode a container ``libsndfile`` cannot open, through the ``ffmpeg`` binary.

    ``ffmpeg`` is a declared requirement of the product (``AGENTS.md``), and the download layer
    already shells out to it to remux explicit FLAC streams, so this adds no new kind of
    dependency — it only moves the AAC decode onto a tool that is guaranteed present rather than
    onto a Python package whose support for it varies by release.

    The audio is decoded to a float WAV in a temporary file and read back with the same
    ``soundfile`` reader the primary path uses, which keeps one decode shape for both paths and
    preserves the source's native rate and channel count.  A pipe was rejected deliberately: the
    longer archive items are hours long, so buffering a whole WAV in memory to hand ``soundfile`` a
    seekable object would cost gigabytes, while a temp file costs only the decoded array.

    Three ffmpeg flags are load-bearing, each because a failure was measured rather than imagined:

    * ``-nostdin`` — without a stdin guard ``ffmpeg`` reads the inherited stdin, and ``q`` is its
      quit key (reproduced: a piped ``q\\n`` turned a valid ``.m4a`` into ``AudioDecodeError`` while
      an empty stdin decoded fine).  This flag **and** ``stdin=subprocess.DEVNULL`` below both
      address it, and either alone suffices — measured by removing each independently.  Both are
      kept on purpose: the flag is ffmpeg's own contract and holds however the child is spawned,
      the call-site argument is what a reader of this function sees, and only removing **both**
      brings the bug back (``test_the_ffmpeg_decode_survives_a_piped_quit_key`` fails then).
    * ``-rf64 auto`` — the RIFF/WAVE muxer cannot express a file over 4 GiB and, past that limit,
      ``ffmpeg`` **exits 0** while printing ``Filesize … invalid for wav, output file will be
      broken`` to the stderr this call discards.  Measured on a 11600 s 48 kHz stereo source: the
      WAV held 536 870 911 of 552 000 000 frames and ``soundfile`` read the truncated array without
      raising, so ~3.1 h of audio would vanish silently.  ``-rf64 auto`` writes RF64 only when a
      plain WAV would overflow, and libsndfile reads RF64.
    * ``-v error`` — keeps the child's chatter out of the parent's stderr on the success path.
    """

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ASRDependencyError(
            "reading .m4a/AAC needs the `ffmpeg` binary and it is not on PATH; "
            "install it (e.g. `apt install ffmpeg`) and re-run"
        )

    handle, scratch = tempfile.mkstemp(prefix="bili-asr-decode-", suffix=".wav")
    os.close(handle)
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-v", "error",
                "-nostdin",
                "-y",
                "-i", path,
                "-acodec", "pcm_f32le",
                "-rf64", "auto",
                scratch,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
            reason = detail[-1] if detail else f"ffmpeg exited {completed.returncode}"
            # Only the LAST stderr line is reported, and that is load-bearing rather than incidental:
            # ffmpeg's middle line echoes the offending path verbatim ("Error opening input file
            # /tmp/…m4a."), measured for a missing file and for a non-audio file, while its final
            # line is path-free ("Error opening input files: No such file or directory").  The path
            # is deliberately kept out of this message because the product's own convention for an
            # unusable input is a description rather than a location (``audio.py`` says "invalid
            # audio path" and never quotes it), and the caller already knows which item it asked for.
            # So do not "improve" this by joining every line: that would leak the input path, and it
            # would leak ``scratch``'s path too.  Changing to ``detail[0]`` is safer than joining and
            # also more specific, since the first line names the cause; it is not done here because
            # the two cases measured would each need their own check first.
            raise AudioDecodeError(f"ffmpeg could not decode the audio input: {reason}")
        import soundfile as sf

        return sf.read(scratch, dtype="float32")
    finally:
        try:
            os.unlink(scratch)
        except OSError:
            pass


def _read_audio(path: str) -> tuple[Any, int]:
    """Read one audio file to ``(samples, rate)``, mono or ``(samples, channels)``.

    ``soundfile`` is the primary reader and libsndfile reads WAV, FLAC, OGG and MP3 — but not AAC,
    which is the codec inside the ``.m4a`` container this archive's own downloader writes for the
    preferred DASH audio stream.  A format the primary reader cannot open is therefore not a missing
    dependency: it is the documented input, so the reader has to be wide enough for it or the
    product cannot transcribe what it downloaded.

    The fallback is the **``ffmpeg`` binary**, not a Python package.  An earlier revision routed this
    through ``librosa.load`` on the belief that it reaches ``audioread`` and then ``ffmpeg``; that
    chain broke when ``librosa`` 1.0 dropped ``audioread`` and made ``load`` a bare ``soundfile``
    call, so the fallback silently re-raised the very error it existed to catch while every test
    still passed (residual ``iter-2026-09-qwen3-asr-closeout · R5``).  ``ffmpeg`` is pinned by the
    platform rather than by a version range, and the archive already requires it.

    The returned shape is the one ``soundfile.read`` returns, so the caller's channel collapse and
    resample stay the only place that shaping happens.
    """

    import numpy as np
    import soundfile as sf

    try:
        return sf.read(path, dtype="float32")
    except sf.LibsndfileError:
        samples, rate = _decode_with_ffmpeg(path)
        return np.asarray(samples, dtype=np.float32), int(rate)


def _clean_text(text: str) -> str:
    """The recognised text without control markers, in one line."""

    return _RICH_TAG.sub("", str(text)).strip()


def _body(text: str) -> str:
    """The part of a line that carries meaning, without its closing marks."""

    return str(text).strip(_CUE_CLOSING_MARKS).strip()


def _join_text(left: str, right: str) -> str:
    """Join two cue texts, keeping a separator between Latin words.

    The decoder does not always carry the space between English words, so absorbing a fragment into
    the cue before it must not glue them together.  Chinese text is unaffected: the space is only
    added between two ASCII alphanumerics.
    """

    if (
        left
        and right
        and left[-1].isascii()
        and left[-1].isalnum()
        and right[0].isascii()
        and right[0].isalnum()
    ):
        return f"{left} {right}"
    return left + right


# ---------------------------------------------------------------------------------------
# The two pure steps the pipeline is built from.  Both are engine-independent and testable
# without a model; everything else in this module is plumbing around them.
# ---------------------------------------------------------------------------------------


def _split_audio(samples: Any, sample_rate: int, max_chunk_seconds: float) -> list[tuple[Any, float]]:
    """Cut a waveform into chunks near ``max_chunk_seconds``, at low-energy boundaries.

    Returns ``(chunk_samples, offset_seconds)`` pairs in order whose lengths **tile the input
    exactly**: no overlap, no gap, nothing dropped and nothing added.  Padding a degenerate chunk up
    to the aligner's minimum is the caller's business, not the splitter's, precisely so that promise
    stays checkable.
    """

    import numpy as np

    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.mean(-1).astype(np.float32)
    total = int(samples.shape[0])
    if total <= 0:
        return []
    if total / float(sample_rate) <= max_chunk_seconds:
        return [(samples, 0.0)]

    max_len = int(max_chunk_seconds * sample_rate)
    expand = int(_CHUNK_SEARCH_EXPAND_S * sample_rate)
    window = max(4, int((_CHUNK_MIN_WINDOW_MS / 1000.0) * sample_rate))

    chunks: list[tuple[Any, float]] = []
    start = 0
    offset = 0.0
    while (total - start) > max_len:
        cut = start + max_len
        # The boundary may only be searched where the window is centred AND clear of the current
        # start.  Otherwise the quietest point lands on the window's edge — measured: a 3.01 s
        # recording came back as 161 chunks of ~4 samples, and merely flooring the progress at one
        # window turned that into a run of 100 ms chunks.  When the window cannot be centred, the
        # cut itself is the only honest boundary.
        left = cut - expand
        right = min(total, cut + expand)
        if left <= start or right - left <= window:
            boundary = cut
        else:
            segment = np.abs(samples[left:right])
            windows = np.convolve(segment, np.ones(window, dtype=np.float32), mode="valid")
            quietest = int(np.argmin(windows))
            boundary = left + quietest + int(np.argmin(segment[quietest:quietest + window]))
            boundary = max(boundary, start + window)
        boundary = max(boundary, start + 1)
        boundary = min(boundary, total)
        chunks.append((samples[start:boundary], offset))
        offset += (boundary - start) / float(sample_rate)
        start = boundary
    chunks.append((samples[start:total], offset))
    return chunks


def _thread_text(text: str, units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the recognised text's marks back onto the aligned units.

    The aligner times the units it is given, and for Chinese those are the characters **without
    punctuation**: a mark has no audio to align to, so it never comes back in the unit list.  The
    archive's product is the recognised text, so every character of ``text`` is threaded back here —
    exactly once, in order — with a timeable unit keeping its own timing and a mark inheriting the
    instant of the piece beside it.  This step is what keeps the FunASR-era rule "cue text is the
    recognised text verbatim" true; without it both the marks and the sentence-ending rule that
    closes cues on them are lost (measured: 287 vs ~983 cues on a 47-minute item, and 1 224 marks
    missing).
    """

    pieces: list[dict[str, Any]] = []
    index = 0
    position = 0
    while position < len(text):
        unit = units[index] if index < len(units) else None
        unit_text = _clean_text(unit.get("text", "")) if isinstance(unit, dict) else ""
        if unit_text and text.startswith(unit_text, position):
            pieces.append({
                "text": unit_text,
                "start": float(unit["start_time"]),
                "end": float(unit["end_time"]),
            })
            position += len(unit_text)
            index += 1
            continue
        anchor = pieces[-1]["end"] if pieces else (
            float(units[index]["start_time"]) if index < len(units) else 0.0
        )
        pieces.append({"text": text[position], "start": anchor, "end": anchor})
        position += 1
    # A unit the text does not account for should not exist; if one does it is kept rather than
    # dropped, and naming that case is the audit's job, not this function's.
    for unit in units[index:]:
        if isinstance(unit, dict) and _clean_text(unit.get("text", "")):
            pieces.append({
                "text": _clean_text(unit["text"]),
                "start": float(unit["start_time"]),
                "end": float(unit["end_time"]),
            })
    return pieces


def _aligned_cues(pieces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape threaded pieces into subtitle cues, in one pass.

    This is the FunASR-era state machine (plan §13.2), re-driven by aligned pieces instead of FunASR
    tokens: the rules were measured on this corpus and are product decisions, so only their input
    changed.  A cue closes on a sentence-ending mark, when :data:`_CUE_MAX_CHARS` is reached, or on a
    pause of at least :data:`_CUE_MAX_GAP_SECONDS` **in a cue that can already stand on its own**; a
    cue that is still only marks, or below :data:`_CUE_MIN_CHARS` / :data:`_CUE_MIN_SECONDS`, is
    absorbed by the cue before it; and a closing mark that arrives at a boundary is handed back to
    the cue it closes.  Nothing shapes the text a second time, and nothing is dropped.
    """

    cues: list[dict[str, Any]] = []
    parts: list[str] = []
    start: float | None = None
    last_end: float | None = None
    pending = ""  # text the cue before it could not take

    def formed() -> bool:
        return (
            len(_body("".join(parts))) >= _CUE_MIN_CHARS
            and (last_end or 0.0) - (start or 0.0) >= _CUE_MIN_SECONDS
        )

    def reset() -> None:
        nonlocal parts, start, last_end, pending
        parts, start, last_end, pending = [], None, None, ""

    def hand_back(piece: str, end: float) -> None:
        """Give a closing mark to the cue it actually closes."""

        cues[-1]["text"] = _join_text(str(cues[-1]["text"]), piece)
        cues[-1]["end"] = max(float(cues[-1]["end"]), end)

    def close() -> None:
        nonlocal pending
        text = _clean_text(pending + "".join(parts))
        if not text:
            reset()
            return
        span = last_end if last_end is not None else (start or 0.0)
        undersized = len(_body(text)) < _CUE_MIN_CHARS or (span - (start or 0.0)) < _CUE_MIN_SECONDS
        if cues and (undersized or not _body(text)):
            # a fragment joins the cue before it: the character ceiling is a readability target,
            # and losing text to it would be worse
            previous = cues[-1]
            previous["text"] = _join_text(str(previous["text"]), text)
            previous["end"] = max(float(previous["end"]), span)
            reset()
            return
        cues.append({"start": start, "end": span, "text": text})
        reset()

    def append_piece(text: str) -> None:
        """Append one aligned fragment, repairing omitted Latin separators at the boundary."""

        if not parts:
            parts.append(text)
        else:
            # Qwen's aligner may return one word per piece without the whitespace that was
            # present in the recognised text.  Apply the same boundary rule used when cues
            # are merged, before length/closing decisions inspect the accumulated text.
            parts[-1] = _join_text(parts[-1], text)

    for piece in pieces:
        if not isinstance(piece, dict):
            continue
        text = str(piece.get("text") or "")
        if not text:
            continue
        begin, end = float(piece["start"]), float(piece["end"])
        mark = text.strip()
        if start is None:
            # a closing mark never opens a cue: it belongs to the cue it closes
            if mark and mark[0] in _CUE_CLOSING_MARKS:
                if cues:
                    hand_back(text, end)
                else:
                    pending += text
                continue
            start = begin
        elif begin - (last_end if last_end is not None else begin) >= _CUE_MAX_GAP_SECONDS and formed():
            close()
            if mark and mark[0] in _CUE_CLOSING_MARKS and cues:
                hand_back(text, end)
                continue
            start = begin
        append_piece(text)
        last_end = end
        if mark in _SENTENCE_ENDINGS or len(pending + "".join(parts)) >= _CUE_MAX_CHARS:
            close()
    close()
    return cues


def _characters_from_pieces(
    pieces: list[dict[str, Any]], cues: list[dict[str, Any]]
) -> dict[str, Any]:
    """The character-level record for ``cues`` built from ``pieces``.

    ``_thread_text`` is the last step that still knows which character of the transcript each
    instant belongs to: ``_aligned_cues`` projects that stream onto readable cue text and, in
    doing so, drops the whitespace that sat on a cue boundary (measured on one real 47-minute
    item: 98 characters, and every one of them whitespace).  So the record cannot be a dump of
    the pieces — it is the pieces **projected onto the published cue text**, walked in step so
    every character of that text keeps the instant the aligner gave it.

    A character the cue text carries and the pieces do not — the separator ``_join_text``
    inserts between two Latin words — inherits the instant of the piece beside it, the same
    rule a punctuation mark gets in :func:`_thread_text`.  A character neither stream explains
    raises :class:`ValueError`: the record would be a claim about the cue text that the cue
    text contradicts.

    Seconds, like ``segments``, and three parallel arrays rather than one dict per character.  The
    size argument is in the plan's D-5 correction, not here: the shape choice is not what drives the
    cost (the dominant term is the digit count of the timestamps themselves, and the writer's
    pretty-printing), which is why an earlier version of this docstring quoted a figure the plan has
    since withdrawn.
    """

    text = "".join(str(cue.get("text", "")) for cue in cues)
    stream: list[tuple[str, float, float]] = [
        (character, float(piece["start"]), float(piece["end"]))
        for piece in pieces
        for character in str(piece.get("text", ""))
    ]
    starts: list[float] = []
    ends: list[float] = []
    index = 0
    anchor = stream[0][1] if stream else 0.0
    for position, character in enumerate(text):
        # Whitespace the cue text does not carry: it sat on a cue boundary and was stripped.
        while index < len(stream) and stream[index][0] != character and stream[index][0].isspace():
            index += 1
        if index < len(stream) and stream[index][0] == character:
            start, end = stream[index][1], stream[index][2]
            index += 1
            anchor = end
        elif character.isspace():
            start = end = anchor
        else:
            raise ValueError(
                "the cue text is not a projection of the threaded pieces: "
                f"character {position} is in no piece"
            )
        starts.append(start)
        ends.append(end)
    if any(not character.isspace() for character, *_ in stream[index:]):
        raise ValueError(
            "the cue text is not a projection of the threaded pieces: "
            f"{len(stream) - index} piece characters are not in the cue text"
        )
    return {"text": text, "starts": starts, "ends": ends}


def _coverage_record(
    decoded_seconds: float, cues: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The coverage evidence for one run, or ``None`` when there is nothing to claim.

    ``decoded_seconds`` is ``sum(len(chunk) / SAMPLE_RATE)`` over **that run's** ``_split_audio``
    output — a measured quantity, not a header/container guess, and exactly what
    :class:`AudioDecodeError`'s documented gap says was missing.  The splitter's tiling promise
    makes that sum equal the decoded sample count, so the denominator needs no tolerance band and
    a shortfall stays attributable to the model rather than to the split.

    ``produced_s`` is ``max(cue.end) - min(cue.start)`` — a **span**, not a span-sum, so
    duplicate or overlapping cues cannot inflate coverage.  ``coverage`` is compared **unrounded**.

    ``None`` means "no coverage claim at all" (``decoded_s == 0``): a run that decoded nothing has
    nothing to attest, and inventing a ratio there would be a claim about audio nobody read.
    """

    if decoded_seconds <= 0:
        return None
    if cues:
        produced = max(float(cue["end"]) for cue in cues) - min(
            float(cue["start"]) for cue in cues
        )
    else:
        # A run that produced no cue at all covers 0 of what it decoded — the same rule that makes
        # an empty transcript with a non-zero decode a shortfall rather than a no-speech outcome.
        produced = 0.0
    # Alignment timestamps can overshoot the decoded window.  Keep the derived
    # evidence within the storage contract; published cue timestamps stay intact.
    produced = min(produced, decoded_seconds)
    coverage = produced / decoded_seconds
    return {
        "decoded_s": float(decoded_seconds),
        "produced_s": float(produced),
        "coverage": float(coverage),
        "coverage_min": COVERAGE_MIN,
        "coverage_short": bool(coverage < COVERAGE_MIN),
    }


def apply_provenance_evidence(entry: dict[str, Any], runner: Any) -> None:
    """Carry the ASR branch's provenance on its resumable manifest row."""
    try:
        provenance = runner.provenance() or {}
    except Exception:
        provenance = {}
    entry["source"] = "asr"
    entry["language"] = provenance_language(provenance)


def apply_coverage_evidence(entry: dict[str, Any], runner: Any) -> dict[str, Any] | None:
    """Write the last run's coverage evidence onto a manifest row, in place.

    The one writer helper both routes share (the in-process ``asr``/``pilot`` loops and
    :class:`RunCoordinator`): the evidence is a property of the **run**, so it must reach the row
    through every path that ran ASR, and a path that forgot it would leave a measured defect
    looking like an unqualified success.

    The previous run's keys are cleared first, so a re-run that measured nothing cannot leave an
    older run's ``coverage`` standing as if it described this one — an unqualified success cannot
    be laundered and cannot be inherited either (spec rule 6).

    The carrier is the manifest row itself (D11): ``decoded_s`` / ``produced_s`` / ``coverage`` /
    ``coverage_min`` beside the existing outcome vocabulary, plus the boolean marker
    ``coverage_short``.  No new ``outcome`` and no new ``error_code`` value — the existing CHECK
    constraint and the Python guards refuse those on every existing database, and the schema is
    ``CREATE TABLE IF NOT EXISTS`` with no in-place migration.

    Returns the record that was written, or ``None`` when the runner has no measurement to offer
    (it never transcribed, or it decoded nothing).
    """

    for key in COVERAGE_KEYS:
        entry.pop(key, None)
    reader = getattr(runner, "transcribed_coverage", None) if runner is not None else None
    record = reader() if callable(reader) else None
    if not record:
        return None
    entry.update(record)
    return record


def coverage_verdict(entry: Any) -> str:
    """One archived row's coverage verdict, read-only, from the archive alone.

    Three values, and the third is the point: a record with no ``coverage`` is
    :data:`COVERAGE_VERDICT_NOT_EVALUABLE` — *not* "covered" and *not* clean.  Reading an absent
    field as "no gap" would call every pre-existing row fine, which is the illusion this plan
    removes; the store persists no decoded duration for those rows, so their coverage is not
    reconstructible and the honest answer is the partition, not a guess.
    """

    if not isinstance(entry, dict):
        return COVERAGE_VERDICT_NOT_EVALUABLE
    coverage = entry.get("coverage")
    if isinstance(coverage, bool) or not isinstance(coverage, (int, float)):
        return COVERAGE_VERDICT_NOT_EVALUABLE
    return (
        COVERAGE_VERDICT_SHORT
        if float(coverage) < COVERAGE_MIN
        else COVERAGE_VERDICT_COVERED
    )


# ---------------------------------------------------------------------------------------
# The model set and the runner
# ---------------------------------------------------------------------------------------


class _ModelSet(NamedTuple):
    """The two processors and two models one runner owns."""

    processor: Any
    model: Any
    aligner_processor: Any
    aligner: Any


def _load_qwen_models(**kwargs: Any) -> _ModelSet:
    """Build the ASR + aligner pair, lazily and once per runner.

    This is the one place transformers is imported.  The two checkpoints are loaded together so that
    a runner either has a working pair or none — a half-loaded pair would report a construction the
    run cannot use.
    """

    try:
        import torch
        from transformers import (
            AutoModelForMultimodalLM,
            AutoModelForTokenClassification,
            AutoProcessor,
        )
    except ImportError as exc:
        raise ASRDependencyError(
            f"Qwen3-ASR support is not installed; run: {_INSTALL_HINT}"
        ) from exc

    model_name = kwargs["model_name"]
    aligner_name = kwargs["aligner_name"]
    device = kwargs.get("device") or "cuda"
    revision = kwargs.get("model_revision")

    processor = AutoProcessor.from_pretrained(model_name, revision=revision)
    model = AutoModelForMultimodalLM.from_pretrained(
        model_name, revision=revision, dtype=torch.bfloat16, device_map=device
    )
    aligner_processor = AutoProcessor.from_pretrained(aligner_name, revision=revision)
    aligner = AutoModelForTokenClassification.from_pretrained(
        aligner_name, revision=revision, dtype=torch.bfloat16, device_map=device
    )
    model.eval()
    aligner.eval()
    return _ModelSet(processor, model, aligner_processor, aligner)


class ASRRunner:
    """Lazy owner of the model pair for sequential use within one run scope.

    ``model_constructions`` counts the **model sets** this runner built — one per lazy construction,
    zero when the run never needed audio.  That keeps the observable run-scoped reuse contract
    unchanged after the two-model switch: a batch that reuses one runner reports **one** construction
    for N items, because the aligner rides in the same set.

    ``model_load_attempts`` is the attempt counter beside it: a load the factory rejected is retried
    once per row — bounded by :data:`MAX_MODEL_LOAD_ATTEMPTS` — pays no construction, and is counted
    here instead.  The invariant is ``model_load_attempts >= model_constructions``, with equality when
    every load succeeded.
    """

    def __init__(
        self,
        config: ASRConfig | str | None = None,
        *,
        model_factory: Callable[..., Any] | None = None,
        model_name: str | None = None,
    ) -> None:
        if config is None:
            config = ASRConfig(model_name=model_name or DEFAULT_MODEL)
        elif isinstance(config, str):
            if model_name is not None:
                raise TypeError("model_name cannot accompany a model name")
            config = ASRConfig(model_name=config)
        elif model_name is not None:
            raise TypeError("model_name is only accepted without a config")
        if not isinstance(config, ASRConfig):
            raise TypeError("config must be an ASRConfig")
        self.config = config
        self._model_factory = model_factory
        self._models: _ModelSet | None = None
        # Monotonic, never reset by release(): a runner that released and rebuilt paid two
        # constructions, and the count must say so.
        self.model_constructions = 0
        # Attempts, not successes: a failed load is retried once per row, so
        # ``attempts - constructions`` is exactly the number of load failures this runner paid for.
        self.model_load_attempts = 0
        # Run-scoped hotword state (governance ruling 2026-09-28).  ``None`` means
        # "no evidence supplied yet": no guard has run, so the configured list is
        # used verbatim — the state of every caller that predates the guard.  Once
        # evidence arrives, ``_hotwords_effective`` is exactly what the guard admitted
        # and ``_hotwords_dropped`` is ledger-visible.
        self._hotwords_effective: tuple[str, ...] | None = None
        self._hotwords_dropped: tuple[str, ...] = ()
        self._hotwords_evidence_text: str | None = None
        self._hotwords_subtitle_text: str | None = None
        # The character-level record of the last successful ``transcribe`` (see ``characters()``).
        self._last_characters: dict[str, Any] | None = None
        # The cue list of the last successful ``transcribe`` (see
        # ``transcribed_segments()``).  The store write-back converts these
        # into transcript segments; it is cleared on failure like the character
        # record, so a caller never stores a stale transcript.
        self._last_transcribed_segments: list[dict[str, Any]] | None = None
        # The coverage measurement of the same run (see ``transcribed_coverage()``).  ``None``
        # means "no measurement to offer": the run never transcribed, or it decoded nothing.
        self._last_coverage: dict[str, Any] | None = None
        self._last_language: str | None = None

    def _get_models(self) -> _ModelSet:
        if self._models is not None:
            return self._models

        if self.config.device.startswith("cuda"):
            try:
                import torch
            except ImportError:
                raise ASRDependencyError(
                    "PyTorch is required for GPU inference but not installed. "
                    "Install with: pip install torch"
                ) from None
            if not torch.cuda.is_available():
                raise ASRDependencyError(
                    "CUDA/ROCm is not available: no device is visible to PyTorch. "
                    "Run the environment check from the product directory with the venv's "
                    'interpreter (`"$VENV/bin/python" scripts/check_asr_env.py`); it names the '
                    "stage that fails and prints the fix, and `docs/wsl-rocm-gpu.md` carries the "
                    "verified AMD/WSL ROCm recipe. To transcribe without a device, set "
                    "`BILI_ASR_DEVICE=cpu`."
                )

        factory = self._model_factory or _load_qwen_models
        kwargs: dict[str, Any] = {
            "model_name": self.config.model_name,
            "aligner_name": self.config.aligner_name,
            "device": self.config.device,
        }
        if self.config.model_revision is not None:
            kwargs["model_revision"] = self.config.model_revision

        try:
            # Counted *before* the call, so every factory invocation is an attempt whether it
            # returned a pair or raised.  ``_models`` stays None on failure and the next row retries
            # the same call, which is why the attempt counter and the construction counter must not
            # be the same number.
            if self.model_load_attempts >= MAX_MODEL_LOAD_ATTEMPTS:
                raise ASRModelError(
                    "Qwen3-ASR model load failed; check the configured local checkpoints. "
                    f"Gave up after {MAX_MODEL_LOAD_ATTEMPTS} failed load attempt(s)."
                )
            self.model_load_attempts += 1
            self._models = factory(**kwargs)
        except (ASRDependencyError, ASRModelError):
            raise
        except Exception:
            raise ASRModelError(
                "Qwen3-ASR model load failed; check the configured local checkpoints."
            ) from None
        # Counted only here, after the factory returned a pair: a failed load paid no construction.
        self.model_constructions += 1
        return self._models

    # -- the pipeline ------------------------------------------------------------------

    def _transcribe_chunk(
        self, models: _ModelSet, audio_path: str, *, bust_cache: bool = False
    ) -> tuple[str, str]:
        """One chunk through the decoder: ``(text, detected_language)``.

        ``bust_cache`` is the per-pass cache control: ``True`` disables the transformers
        dynamic prefix cache for this decode (``use_cache=False``, the documented
        per-call argument on ``generate`` for the pinned ``transformers>=5.13``), so a
        re-decode with a re-seeded prompt — the two-pass hotword contract's pass 2 — starts
        from a clean model/cache state instead of being served pass 1's cached span, where
        the re-seeded vocabulary never reaches the prompt.  ``False`` keeps the default
        (cache-warm) behaviour for ordinary decodes.

        The decode format matters: ``decode(..., return_format=...)`` hard-sets
        ``skip_special_tokens``, and the decoded text is scrubbed of control markers as well — a
        caller that re-parses a *raw* decode instead would carry ``<|im_end|>`` into the archive.
        """

        import torch

        hotwords = self._prompt_hotwords()
        prompt = "Vocabulary: " + ", ".join(hotwords) if hotwords else None
        inputs = models.processor.apply_transcription_request(
            audio=audio_path, language=self.config.language, prompt=prompt
        )
        inputs = inputs.to(models.model.device, models.model.dtype)
        seconds = float(inputs["input_features_mask"].sum(-1).max()) / _MEL_FRAMES_PER_SECOND
        budget = max(_MIN_NEW_TOKENS, int(seconds * _MAX_NEW_TOKENS_PER_AUDIO_SECOND))
        with torch.inference_mode():
            generated = models.model.generate(**inputs, max_new_tokens=budget, **(
                {"use_cache": False} if bust_cache else {}
            ))
        tokens = generated[:, inputs["input_ids"].shape[1]:]
        text = _clean_text(models.processor.decode(tokens, return_format="transcription_only")[0])
        parsed = models.processor.decode(tokens, return_format="parsed")[0]
        return text, str(parsed.get("language") or "")

    def _align_chunk(self, models: _ModelSet, audio_path: str, text: str, language: str) -> list[dict[str, Any]]:
        """One chunk through the aligner: per-unit ``{text, start_time, end_time}`` in seconds."""

        import torch

        inputs, word_lists = models.aligner_processor.prepare_forced_aligner_inputs(
            audio=audio_path, transcript=text, language=language or "Chinese"
        )
        inputs = inputs.to(models.aligner.device, models.aligner.dtype)
        with torch.inference_mode():
            logits = models.aligner(**inputs).logits
        return list(models.aligner_processor.decode_forced_alignment(
            logits=logits,
            input_ids=inputs["input_ids"],
            word_lists=word_lists,
            timestamp_token_id=models.aligner.config.timestamp_token_id,
        )[0])

    def characters(self) -> dict[str, Any] | None:
        """The character-level record for the **last** :meth:`transcribe`, or ``None``.

        A by-product of the same run rather than a second pass: :meth:`transcribe` already holds
        the threaded pieces (the last step that knows each character's instant) and the cues it
        built from them, so the record costs one walk over the transcript and no model call.
        ``None`` means no transcription has run — the record is not invented for audio the
        runner never read.
        """

        return self._last_characters

    def transcribed_segments(self) -> list[dict[str, Any]] | None:
        """The cue list for the **last** :meth:`transcribe`, or ``None``.

        The store write-back converts these into transcript segments; the list
        is the same object :meth:`transcribe` returned, so the caller archives
        and stores one transcript.  ``None`` means no transcription has run.
        """

        return self._last_transcribed_segments

    def transcribed_coverage(self) -> dict[str, Any] | None:
        """The coverage evidence for the **last** :meth:`transcribe`, or ``None``.

        ``None`` means the run has no measurement to offer — it never transcribed, or it decoded
        nothing (``decoded_s == 0``), in which case no coverage claim is made at all.  The shape is
        the record :func:`_coverage_record` builds; :func:`apply_coverage_evidence` is the one
        place that carries it onto a manifest row.

        Not to be confused with the record of an *earlier* run: the pair is cleared together with
        the other ``_last_*`` state, so a failed call leaves no stale measurement behind.
        """

        return self._last_coverage

    def transcribe(self, audio_path: str, *, bust_cache: bool = False) -> list[dict[str, Any]]:
        """Transcribe one audio file into timestamped cues.

        Every cue the caller receives traces to an aligner call over the audio that produced its
        text: chunk boundaries are ours, the timings are the aligner's, and nothing is interpolated.
        An empty recording yields no cues rather than a fabricated one.

        ``bust_cache`` re-decodes from a clean model/cache state (the per-pass cache control,
        see :meth:`_transcribe_chunk`): it is the pass-2 knob of the two-pass hotword contract —
        the re-seeded prompt is only effective if the re-decode does not reuse pass 1's cache.

        The character-level record of the same run is left for :meth:`characters`; callers that
        publish it read it right after this returns.  The coverage measurement of the same run is
        left for :meth:`transcribed_coverage`, on the same rule — a by-product of the run, not a
        second pass, and not part of the returned cue list.
        """

        # The record describes one run: a call that fails leaves no stale one behind for a caller
        # that reads ``characters()`` after a later, unrelated failure.  The coverage measurement
        # is part of that record, so it is cleared with it.
        self._last_characters = None
        self._last_transcribed_segments = None
        self._last_coverage = None
        self._last_language = None
        # The model pair first: a host without the extra must fail with the documented
        # ``ASRDependencyError`` (which names the ``[asr]`` install), not with whatever the audio
        # reader happens to import first.  The readers are part of the same extra, so their absence
        # is reported the same way.
        models = self._get_models()
        try:
            import numpy as np
            import soundfile as sf
            import soxr
        except ImportError as exc:
            raise ASRDependencyError(
                f"the ASR audio readers are not installed; run: {_INSTALL_HINT}"
            ) from exc

        path, temporary = _materialize_input(audio_path)
        scratch: str | None = None
        try:
            samples, rate = _read_audio(path)
            samples = np.asarray(samples, dtype=np.float32)
            if samples.ndim > 1:
                samples = samples.mean(-1).astype(np.float32)
            if int(rate) != SAMPLE_RATE:
                # ``soxr`` is what ``librosa.resample`` calls underneath at its default
                # ``res_type="soxr_hq"``; measured bit-identical on this corpus, and it drops a
                # dependency whose version range could change the resampler silently.
                samples = soxr.resample(samples, int(rate), SAMPLE_RATE)
                samples = np.asarray(samples, dtype=np.float32)

            chunks = _split_audio(samples, SAMPLE_RATE, self.config.chunk_seconds)
            if not chunks:
                self._last_characters = None
                self._last_transcribed_segments = None
                self._last_coverage = None
                return []

            # The run's own decoded duration: the measured quantity the coverage comparison is
            # against, and — because ``_split_audio`` tiles the input exactly — exactly the number
            # of samples this run fed the model.  Taken before the loop so a chunk that decodes to
            # nothing (``if not text: continue`` below) still counts in the denominator: that
            # branch is where the measured defect's span went missing.
            decoded_seconds = sum(len(chunk) / SAMPLE_RATE for chunk, _offset in chunks)

            handle, scratch = tempfile.mkstemp(prefix="bili-asr-chunk-", suffix=".wav")
            os.close(handle)
            minimum = int(_CHUNK_MIN_SECONDS * SAMPLE_RATE)
            pieces: list[dict[str, Any]] = []
            languages: set[str] = set()
            for chunk, offset in chunks:
                audio = np.asarray(chunk, dtype=np.float32)
                if audio.shape[0] < minimum:
                    # The aligner refuses a degenerate window.  The splitter deliberately does not
                    # pad — that would break its tiling promise — so the pad happens here, where the
                    # requirement comes from.
                    audio = np.pad(audio, (0, minimum - audio.shape[0]))
                sf.write(scratch, audio, SAMPLE_RATE)
                text, language = self._transcribe_chunk(models, scratch, bust_cache=bust_cache)
                if not text:
                    # The silent point the plan names: an empty-transcript chunk is dropped with
                    # no record of its own.  It is not tracked here either — the run-level
                    # comparison below is what makes the drop visible, and it does so without
                    # changing this branch's behaviour or aborting the run.
                    continue
                if language.strip():
                    languages.add(language.strip())
                units = [
                    {
                        "text": unit["text"],
                        "start_time": float(unit["start_time"]) + offset,
                        "end_time": float(unit["end_time"]) + offset,
                    }
                    for unit in self._align_chunk(models, scratch, text, language)
                ]
                pieces.extend(_thread_text(text, units))
            cues = _aligned_cues(pieces)
            # The pieces are the character-level truth and the cues are the published text; the
            # record is the former projected onto the latter, so the two cannot disagree.
            self._last_characters = _characters_from_pieces(pieces, cues)
            self._last_transcribed_segments = list(cues)
            # The run's coverage evidence, measured from what this run decoded and what it
            # produced.  It rides the manifest row (D11 carrier); the return shape of this method
            # is deliberately unchanged.
            self._last_coverage = _coverage_record(decoded_seconds, cues)
            # Preserve the engine's detected language for automatic-language
            # runs. Multiple languages are explicit; no evidence stays unset.
            if len(languages) == 1:
                self._last_language = next(iter(languages))
            elif languages:
                self._last_language = "mul"
            return cues
        finally:
            for leftover in (temporary, scratch):
                if leftover:
                    try:
                        os.unlink(leftover)
                    except OSError:
                        pass

    def release(self) -> None:
        """Drop the owned model pair.  The counters are monotonic and are **not** reset."""

        self._models = None

    def _prompt_hotwords(self) -> tuple[str, ...]:
        """The vocabulary that may reach the prompt for the next chunk.

        ``self.config.hotwords`` is the operator's configured list; the effective
        list is what the evidence guard admitted once evidence was supplied.  A
        runner that never received evidence keeps its configured list verbatim.
        """

        return (
            self.config.hotwords
            if self._hotwords_effective is None
            else self._hotwords_effective
        )

    @property
    def hotwords_dropped(self) -> tuple[str, ...]:
        """Terms the evidence guard refused for this run (ledger-visible)."""

        return self._hotwords_dropped

    def set_hotword_evidence(
        self,
        *,
        evidence_text: str | None,
        paired_subtitle_text: str | None,
    ) -> None:
        """Run the evidence guard over the configured list and remember the verdict.

        ``evidence_text`` is the run's own first-pass transcript; ``paired_subtitle_text``
        is the AI-subtitle text for the same part (``None`` when the part has no
        subtitle route).  Both are evidence — a token occurring in either survives.
        Idempotent for the same evidence: the guard is pure string logic, so the
        same input yields the same verdict and re-setting is a no-op.
        """

        admitted, dropped = filter_hotwords(
            self.config.hotwords,
            evidence_text=evidence_text,
            paired_subtitle_text=paired_subtitle_text,
        )
        # Idempotence: re-applying the *same* evidence is a no-op (the guard is
        # pure string logic, so the same input yields the same verdict).  A
        # genuinely different evidence — a real first-pass transcript versus a
        # later, fuller one — re-seeds and the recorded fact is replaced.
        if (
            self._hotwords_effective is not None
            and (evidence_text, paired_subtitle_text)
            == (self._hotwords_evidence_text, self._hotwords_subtitle_text)
        ):
            return
        self._hotwords_effective = admitted
        self._hotwords_dropped = dropped
        self._hotwords_evidence_text = evidence_text
        self._hotwords_subtitle_text = paired_subtitle_text

    def rebuild_hotwords_from_first_pass(self, transcript_text: str) -> list[str]:
        """Reseed the prompt vocabulary from the run's own first-pass transcript.

        The two-pass contract (plan 20260928-hotword-injection-governance, Task 1):
        a first pass over the audio with the guard's *configured* list produces a
        transcript; only tokens that transcript itself contains are admitted for the
        second pass — evidence-based seeding replacing speculative seeding.  Tokens
        without an occurrence are recorded under ``hotword_dropped_no_evidence`` in
        :meth:`provenance`.

        Returns the KEPT tokens — the reseeded vocabulary that will bias the
        second pass.  (An earlier shape returned the dropped list, which made
        every caller run pass 2 unconditionally: a pass-1 transcript never
        equals the pre-pass-1 paired-subtitle evidence, so the dropped list is
        always non-empty whenever any token was subtitle-admitted.  QC F2,
        2026-09-28.)

        Pass 2 is worth its decode cost only when the kept list is non-empty:
        an empty kept list means the guard admits nothing beyond what pass 1
        already produced, and a second decode cannot change the output.
        """

        self.set_hotword_evidence(
            evidence_text=transcript_text, paired_subtitle_text=None
        )
        return [term for term in (self._hotwords_effective or ())]

    def provenance(self) -> dict[str, str]:
        """Redacted configuration and the last successful transcription's language."""

        config = self.config
        provenance = {
            "model_name": _redact(config.model_id or config.model_name),
            "aligner_model": _redact(config.aligner_name),
            "model_revision": _redact(config.model_revision or ""),
            "device": _redact(config.device),
            "language": _redact(self._last_language or config.language or ""),
            "hotwords": _redact(",".join(self._prompt_hotwords())),
            "chunk_seconds": f"{config.chunk_seconds:g}",
            "offline": str(config.offline),
            "local_source": _redact(config.local_source),
        }
        if self._hotwords_dropped:
            provenance["hotword_dropped_no_evidence"] = ",".join(
                _redact(term) for term in self._hotwords_dropped
            )
        return provenance


#: The processor's mel features are 100 frames per second of 16 kHz audio; the token budget per
#: chunk is derived from the actual feature length rather than from a wall-clock guess.
_MEL_FRAMES_PER_SECOND = 100.0


def _redact(value: str) -> str:
    """``[redacted]`` for a value that would publish a path, URL or credential."""

    return "[redacted]" if value and _FORBIDDEN_PROVENANCE.search(value) else value


# ---------------------------------------------------------------------------------------
# Products — the segment renderers and the SRT clock now live in :mod:`bili_asr.cues`
# (plan 009 consolidated the cue parsers); they are re-exported here because
# ``archive.py`` and the test tree import them from this module.  A cue is a
# subtitle line; the shape they consume is ``{"start", "end", "text"}`` in
# seconds.
# ---------------------------------------------------------------------------------------

from .cues import _fmt_srt_time as _fmt_srt_time  # noqa: F401  (deliberate re-export)
from .cues import segments_to_srt as segments_to_srt  # noqa: F401  (deliberate re-export)
from .cues import segments_to_txt as segments_to_txt  # noqa: F401  (deliberate re-export)


def characters_of(runner: Any) -> dict[str, Any] | None:
    """The character-level record ``runner`` produced for its last transcription, if any.

    Read through ``getattr`` because the record is **optional by design**: a runner double that
    never held aligner output answers with nothing, and so does an ASR boundary from before this
    record existed.  Nothing is fabricated for either — the ``characters`` field is only ever a
    captured fact.
    """

    reader = getattr(runner, "characters", None)
    return reader() if callable(reader) else None


def transcribed_coverage(runner: Any) -> dict[str, Any] | None:
    """The coverage evidence ``runner`` measured for its last transcription, if any.

    The module-level counterpart of :meth:`ASRRunner.transcribed_coverage`, and the same shape as
    :func:`characters_of` beside it: read through ``getattr`` so a runner double without the
    method, or an ASR boundary from before this measurement existed, answers with nothing rather
    than fabricating a clean bill.  ``None`` reaches the bundle as *no attestation*, which is the
    truthful record — the frontmatter simply carries no ``coverage_*`` key.

    This is the bundle-side half of the same measurement :func:`apply_coverage_evidence` writes to
    the manifest row; ``I-000188``'s acceptance requires the signal in both surfaces.
    """

    reader = getattr(runner, "transcribed_coverage", None)
    return reader() if callable(reader) else None


def two_pass_transcribe(
    runner: ASRRunner, audio_path: str, *, paired_subtitle_text: str | None
) -> list[dict[str, Any]]:
    """The two-pass hotword decode, shared by every production caller.

    ``paired_subtitle_text`` is the AI-subtitle text for the same part (``None``
    when the part has no subtitle route).  The contract (plan
    20260928-hotword-injection-governance): pass 1 decodes unguarded, the prompt
    is re-seeded with the tokens pass 1 itself produced, and pass 2 re-decodes
    with ``bust_cache=True`` — the re-seeded vocabulary only reaches the model if
    the re-decode does not reuse pass 1's transformers prefix cache.  When the
    guard keeps nothing beyond pass 1's own output, pass 2 cannot change the
    transcript and its cost is skipped: pass 1's segments are the result.
    """

    runner.set_hotword_evidence(
        evidence_text=None, paired_subtitle_text=paired_subtitle_text
    )
    first_pass = runner.transcribe(audio_path)
    transcript_text = "".join(str(seg.get("text", "")) for seg in first_pass)
    if runner.rebuild_hotwords_from_first_pass(transcript_text):  # kept tokens
        return runner.transcribe(audio_path, bust_cache=True)
    return first_pass


# ---------------------------------------------------------------------------------------
# One-shot helpers, kept for the callers that hold no runner.
# ---------------------------------------------------------------------------------------


def transcribe(audio_path: str, model_name: str | None = None) -> list[dict[str, Any]]:
    """Transcribe one file with a fresh runner (one-shot; batches should hold a runner)."""

    config = replace(default_config(), model_name=model_name) if model_name else None
    return ASRRunner(config).transcribe(audio_path)


def provenance() -> dict[str, str]:
    """The provenance of the default configuration."""

    return ASRRunner(default_config()).provenance()
