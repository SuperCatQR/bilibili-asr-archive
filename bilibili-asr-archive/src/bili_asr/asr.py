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
``device_map`` path), ``soundfile``/``librosa`` (reading audio).  Transformers is imported only when a
runner first transcribes; no model download orchestration lives here.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, NamedTuple

DEFAULT_MODEL = "Qwen/Qwen3-ASR-1.7B-hf"
DEFAULT_ALIGNER_MODEL = "Qwen/Qwen3-ForcedAligner-0.6B-hf"

_INSTALL_HINT = 'pip install -e "bilibili-asr-archive/[asr]"'

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

#: Corpus vocabulary carried to the decoder as free-form context (the processor's ``prompt``).
#: Every entry has been observed mis-recognised as a homophone on this archive's own audio
#: (``马鞍牌`` for 马恩牌, ``公式`` for 攻势, ``智力豆包`` for 智利豆包, ``跟着苗红`` for 根正苗红) or is a
#: recurring name of the corpus.  The list stays short on purpose: the terms travel as one prompt
#: line and a long one dilutes the bias.
DEFAULT_HOTWORDS: tuple[str, ...] = (
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
    # TEM / AITM / ITM).  They are listed as whole phrases as well as acronyms so
    # the decoder has both the spelled-out form and the initialisms.
    #
    # The bare acronyms ITEM and AITEM were **removed on 2026-09-17** after the
    # season run measured them doing harm of the kind they were added to prevent:
    # nine occurrences across the 14 archived lectures, e.g. "THE ITEMthat's the
    # question is anITEM ONE", "This is expressed in the finite on the AITEM",
    # "In accessible AITEM distance outside", "就是WHAT IS POSITIVE ITEM" — and
    # every one of them is the acronym capturing a neighbouring word rather than
    # a spoken initialism.  The spelled-out phrase stayed: it appears three times
    # and is genuine each time.
    #
    # Evidence status: the surface-form measurements are the **retired FunASR-Nano**
    # checkpoint's and do not carry over unmeasured; re-measuring this list under the
    # engine that ships, with insertions counted separately from recoveries, is T5.
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
    sends no bias, and the terms are recorded in provenance.

    ``model_name`` / ``aligner_name`` are hub ids or local checkpoint directories.  ``model_id`` is the
    operator's declaration of the hub-level identity behind the ASR checkpoint.
    """

    model_name: str
    aligner_name: str = DEFAULT_ALIGNER_MODEL
    model_revision: str | None = None
    device: str = "cuda"
    language: str | None = None
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

    Retained from the FunASR era (plan §13.1): the original reason was a child ``ffmpeg``, which a
    descriptor cannot be handed to.  Reading is in-process now, so this may be removable — it is kept
    until a run proves descriptor paths work without it.
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


def _read_audio(path: str) -> tuple[Any, int]:
    """Read one audio file to ``(samples, rate)``, mono or ``(samples, channels)``.

    ``soundfile`` is the primary reader and libsndfile reads WAV, FLAC, OGG and MP3 — but not AAC,
    which is the codec inside the ``.m4a`` container this archive's own downloader writes for the
    preferred DASH audio stream.  A format the primary reader cannot open is therefore not a missing
    dependency: it is the documented input, so the reader has to be wide enough for it or the
    product cannot transcribe what it downloaded.

    ``librosa`` is the fallback: already a declared ``[asr]`` dependency, already imported by this
    module for resampling, and decoding through ``audioread`` (an ``ffmpeg`` child, which
    ``AGENTS.md`` already requires).  On the formats both readers open they agree sample-for-sample
    — verified on the target host against an ``ffmpeg -ar 48000 -ac 2`` decode of the same file:
    no length difference and a maximum absolute difference of 0.000000 — so the fallback widens the
    reader rather than trading quality.

    The returned shape is the one ``soundfile.read`` returns, so the caller's channel collapse and
    resample stay the only place that shaping happens.
    """

    import numpy as np
    import soundfile as sf

    try:
        return sf.read(path, dtype="float32")
    except sf.LibsndfileError:
        import librosa

        samples, rate = librosa.load(path, sr=None, mono=False)
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim > 1:
            samples = samples.T  # librosa is (channels, samples); soundfile is (samples, channels)
        return samples, int(rate)


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
        parts.append(text)
        last_end = end
        if mark in _SENTENCE_ENDINGS or len(pending + "".join(parts)) >= _CUE_MAX_CHARS:
            close()
    close()
    return cues


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

    def _transcribe_chunk(self, models: _ModelSet, audio_path: str) -> tuple[str, str]:
        """One chunk through the decoder: ``(text, detected_language)``.

        The decode format matters: ``decode(..., return_format=...)`` hard-sets
        ``skip_special_tokens``, and the decoded text is scrubbed of control markers as well — a
        caller that re-parses a *raw* decode instead would carry ``<|im_end|>`` into the archive.
        """

        import torch

        prompt = "Vocabulary: " + ", ".join(self.config.hotwords) if self.config.hotwords else None
        inputs = models.processor.apply_transcription_request(
            audio=audio_path, language=self.config.language, prompt=prompt
        )
        inputs = inputs.to(models.model.device, models.model.dtype)
        seconds = float(inputs["input_features_mask"].sum(-1).max()) / _MEL_FRAMES_PER_SECOND
        budget = max(_MIN_NEW_TOKENS, int(seconds * _MAX_NEW_TOKENS_PER_AUDIO_SECOND))
        with torch.inference_mode():
            generated = models.model.generate(**inputs, max_new_tokens=budget)
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

    def transcribe(self, audio_path: str) -> list[dict[str, Any]]:
        """Transcribe one audio file into timestamped cues.

        Every cue the caller receives traces to an aligner call over the audio that produced its
        text: chunk boundaries are ours, the timings are the aligner's, and nothing is interpolated.
        An empty recording yields no cues rather than a fabricated one.
        """

        # The model pair first: a host without the extra must fail with the documented
        # ``ASRDependencyError`` (which names the ``[asr]`` install), not with whatever the audio
        # reader happens to import first.  The readers are part of the same extra, so their absence
        # is reported the same way.
        models = self._get_models()
        try:
            import numpy as np
            import soundfile as sf
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
                import librosa

                samples = librosa.resample(samples, orig_sr=int(rate), target_sr=SAMPLE_RATE)
                samples = np.asarray(samples, dtype=np.float32)

            chunks = _split_audio(samples, SAMPLE_RATE, self.config.chunk_seconds)
            if not chunks:
                return []

            handle, scratch = tempfile.mkstemp(prefix="bili-asr-chunk-", suffix=".wav")
            os.close(handle)
            minimum = int(_CHUNK_MIN_SECONDS * SAMPLE_RATE)
            pieces: list[dict[str, Any]] = []
            for chunk, offset in chunks:
                audio = np.asarray(chunk, dtype=np.float32)
                if audio.shape[0] < minimum:
                    # The aligner refuses a degenerate window.  The splitter deliberately does not
                    # pad — that would break its tiling promise — so the pad happens here, where the
                    # requirement comes from.
                    audio = np.pad(audio, (0, minimum - audio.shape[0]))
                sf.write(scratch, audio, SAMPLE_RATE)
                text, language = self._transcribe_chunk(models, scratch)
                if not text:
                    continue
                units = [
                    {
                        "text": unit["text"],
                        "start_time": float(unit["start_time"]) + offset,
                        "end_time": float(unit["end_time"]) + offset,
                    }
                    for unit in self._align_chunk(models, scratch, text, language)
                ]
                pieces.extend(_thread_text(text, units))
            return _aligned_cues(pieces)
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

    def provenance(self) -> dict[str, str]:
        """The redaction-safe provenance of this runner's configuration."""

        config = self.config
        return {
            "model_name": _redact(config.model_id or config.model_name),
            "aligner_model": _redact(config.aligner_name),
            "model_revision": _redact(config.model_revision or ""),
            "device": _redact(config.device),
            "language": _redact(config.language or ""),
            "hotwords": _redact(",".join(config.hotwords)),
            "chunk_seconds": f"{config.chunk_seconds:g}",
            "offline": str(config.offline),
            "local_source": _redact(config.local_source),
        }


#: The processor's mel features are 100 frames per second of 16 kHz audio; the token budget per
#: chunk is derived from the actual feature length rather than from a wall-clock guess.
_MEL_FRAMES_PER_SECOND = 100.0


def _redact(value: str) -> str:
    """``[redacted]`` for a value that would publish a path, URL or credential."""

    return "[redacted]" if value and _FORBIDDEN_PROVENANCE.search(value) else value


# ---------------------------------------------------------------------------------------
# Products — unchanged.  A cue is a subtitle line; these two writers and the SRT clock are what
# ``archive.py`` imports, and the shape they consume is ``{"start", "end", "text"}`` in seconds.
# ---------------------------------------------------------------------------------------


def _fmt_srt_time(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list[dict[str, Any]]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n{_fmt_srt_time(segment['start'])} --> {_fmt_srt_time(segment['end'])}\n"
            f"{segment['text']}\n"
        )
    return "\n".join(blocks)


def segments_to_txt(segments: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(segment.get("text", "")).strip()
        for segment in segments
        if str(segment.get("text", "")).strip()
    )


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
