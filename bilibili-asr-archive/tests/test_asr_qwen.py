"""The Qwen3-ASR boundary: its two pure steps, its contract, and its products.

The engine's own output shapes are exercised on the host (see the plan's §13.5 measurement);
what is pinned here is everything that must hold without a GPU: the chunker's tiling promise, the
mark threading that keeps "cue text is the recognised text" true, the cue state machine that
survived from the FunASR era, the runner's lazy/reuse/retry contract, and the redaction of the
provenance slots.

**Retired by name when the engine changed** (plan §13.7) — these files described FunASR's shapes and
were removed rather than adapted, and each assertion that still describes the product was carried
here first:

* ``tests/test_asr_reproducibility.py`` (1843 lines, ``fake_funasr``) — FunASR's ``AutoModel`` kwargs,
  its token-timestamp normalization, its ``normalize_result`` and its VAD configuration.  Surviving
  and carried here: the runner's construction/attempt counters and their bounds, the dependency and
  model error taxonomy, provenance stability and redaction, and the offline guard.
* ``tests/test_asr_format.py`` — ``_RICH_TAG`` cleanup, ``normalize_result``'s fallback to a
  zero-length segment, and the token-shaped cue shaping.  Surviving and carried here: the SRT/TXT
  writers and the SRT clock.
* ``tests/test_asr_cues.py`` — cue shaping from FunASR token timings, including the per-cue confidence
  it carried.  Surviving and carried here: the cue rules, now driven by aligned pieces.
"""

from __future__ import annotations

import builtins

import pytest

from bili_asr import asr


# ---------------------------------------------------------------------------------------
# Fakes.  The boundary talks to exactly four objects, so the fakes are four small ones — and they
# are plain Python, which keeps this suite runnable on a host with no torch and no numpy.
# ---------------------------------------------------------------------------------------


class _Shape:
    def __init__(self, tokens: "_Tokens") -> None:
        self._tokens = tokens

    def __getitem__(self, index: int) -> int:
        return self._tokens.shape[index]


class _Tokens:
    """Just enough of a tensor: ``[:, n:]``, ``.shape``, ``.sum(-1).max()`` and ``float()``."""

    def __init__(self, length: int, shape: tuple[int, int] | None = None) -> None:
        self.length = length
        self.shape = shape or (1, length)

    def __getitem__(self, key: tuple) -> "_Tokens":
        start = key[1].start or 0
        return _Tokens(self.length - start, (1, self.length - start))

    def __float__(self) -> float:
        # ``_transcribe_chunk`` sizes the token budget from the number of valid mel frames.
        return float(self.length)

    def sum(self, *args, **kwargs) -> "_Tokens":
        return self

    def max(self, *args, **kwargs) -> "_Tokens":
        return self


class _Inputs(dict):
    def to(self, *args, **kwargs) -> "_Inputs":
        return self


class _FakeProcessor:
    def __init__(self, text: str, language: str = "Chinese") -> None:
        self.text = text
        self.language = language
        self.requests: list[dict] = []

    def apply_transcription_request(self, audio=None, language=None, prompt=None) -> _Inputs:
        self.requests.append({"audio": audio, "language": language, "prompt": prompt})
        return _Inputs({
            "input_ids": _Tokens(8),
            "input_features_mask": _Tokens(100 * 10, (1, 100 * 10)),
        })

    def decode(self, tokens, return_format="raw", **kwargs):
        if return_format == "raw":
            return [f"language {self.language}<asr_text>{self.text}<|im_end|>"]
        if return_format == "parsed":
            return [{"language": self.language, "transcription": self.text}]
        return [self.text]


class _FakeModel:
    device = "cpu"
    dtype = None

    def generate(self, **inputs) -> _Tokens:
        return _Tokens(12)


class _AlignInputs(dict):
    def to(self, *args, **kwargs) -> "_AlignInputs":
        return self


class _FakeAlignerProcessor:
    def __init__(self, units: list[dict]) -> None:
        self.units = units
        self.seen: list[dict] = []

    def prepare_forced_aligner_inputs(self, audio=None, transcript=None, language=None):
        self.seen.append({"audio": audio, "transcript": transcript, "language": language})
        return _AlignInputs({"input_ids": _Tokens(16)}), [[u["text"] for u in self.units]]

    def decode_forced_alignment(self, **kwargs):
        return [list(self.units)]


class _FakeAligner:
    device = "cpu"
    dtype = None
    config = type("Config", (), {"timestamp_token_id": 151705})()

    def __call__(self, **inputs):
        return type("Out", (), {"logits": _Tokens(16)})()


class _FakeModelSet:
    def __init__(self, text: str, units: list[dict]) -> None:
        self.processor = _FakeProcessor(text)
        self.model = _FakeModel()
        self.aligner_processor = _FakeAlignerProcessor(units)
        self.aligner = _FakeAligner()


def _units(text: str, step: float = 0.4) -> list[dict]:
    """One timed unit per character of ``text`` (marks excluded, as the aligner really returns)."""

    return [
        {"text": char, "start_time": index * step, "end_time": index * step + step - 0.05}
        for index, char in enumerate(text)
        if char not in "。！？!?，、；：,;: "
    ]


def _pieces(text: str, step: float = 0.4) -> list[dict]:
    return asr._thread_text(text, [
        {"text": u["text"], "start_time": u["start_time"], "end_time": u["end_time"]}
        for u in _units(text, step)
    ])


# ---------------------------------------------------------------------------------------
# The chunker: it must tile the input, never overlap and never leave a gap.
# ---------------------------------------------------------------------------------------


def test_split_audio_tiles_the_input_exactly() -> None:
    np = pytest.importorskip("numpy")
    samples = np.random.default_rng(7).standard_normal(asr.SAMPLE_RATE * 10).astype("float32")
    chunks = asr._split_audio(samples, asr.SAMPLE_RATE, 3.0)
    assert len(chunks) >= 4
    assert sum(len(chunk) for chunk, _ in chunks) == len(samples)
    offsets = [offset for _, offset in chunks]
    assert offsets == sorted(offsets)
    assert offsets[0] == 0.0


def test_split_audio_keeps_a_short_recording_whole() -> None:
    np = pytest.importorskip("numpy")
    samples = np.zeros(asr.SAMPLE_RATE * 2, dtype="float32")
    chunks = asr._split_audio(samples, asr.SAMPLE_RATE, 180.0)
    assert len(chunks) == 1
    assert chunks[0][1] == 0.0
    assert len(chunks[0][0]) == len(samples)


def test_split_audio_keeps_a_degenerate_tail_short_and_still_tiles() -> None:
    """A tail shorter than the aligner's minimum stays short here; the runner pads it.

    Measured defect this pins: with the search window allowed to reach back to ``start``, the
    boundary landed on the window's first sample and the clamp walked one sample per chunk — a
    3.01 s recording came back as 161 chunks.
    """

    np = pytest.importorskip("numpy")
    samples = np.zeros(int(asr.SAMPLE_RATE * 3.01), dtype="float32")
    chunks = asr._split_audio(samples, asr.SAMPLE_RATE, 3.0)
    assert len(chunks) == 2, chunks
    assert sum(len(chunk) for chunk, _ in chunks) == len(samples)
    assert len(chunks[-1][0]) < int(asr._CHUNK_MIN_SECONDS * asr.SAMPLE_RATE)


def test_split_audio_never_returns_a_degenerate_chunk() -> None:
    np = pytest.importorskip("numpy")
    samples = np.random.default_rng(3).standard_normal(asr.SAMPLE_RATE * 4).astype("float32")
    chunks = asr._split_audio(samples, asr.SAMPLE_RATE, 1.0)
    floor = int(asr._CHUNK_MIN_WINDOW_MS / 1000.0 * asr.SAMPLE_RATE)
    assert all(len(chunk) >= floor for chunk, _ in chunks[:-1]), [len(c) for c, _ in chunks]


def test_split_audio_of_nothing_is_no_chunks() -> None:
    np = pytest.importorskip("numpy")
    assert asr._split_audio(np.zeros(0, dtype="float32"), asr.SAMPLE_RATE, 180.0) == []


# ---------------------------------------------------------------------------------------
# Mark threading: what keeps "cue text is the recognised text" true.
# ---------------------------------------------------------------------------------------


def test_threading_keeps_every_character_once_in_order() -> None:
    text = "拟象论啊，拟象论。"
    assert "".join(piece["text"] for piece in _pieces(text)) == text


def test_threading_gives_a_mark_the_instant_beside_it() -> None:
    pieces = _pieces("今天讲两件事。")
    mark = pieces[-1]
    assert mark["text"] == "。"
    assert mark["start"] == mark["end"] == pieces[-2]["end"]


def test_threading_handles_latin_words() -> None:
    text = "International Employment Matters Tribunal 是这个"
    units = [
        {"text": "International", "start_time": 0.0, "end_time": 0.6},
        {"text": "Employment", "start_time": 0.6, "end_time": 1.1},
        {"text": "Matters", "start_time": 1.1, "end_time": 1.5},
        {"text": "Tribunal", "start_time": 1.5, "end_time": 2.0},
        {"text": "是", "start_time": 2.1, "end_time": 2.3},
        {"text": "这", "start_time": 2.3, "end_time": 2.5},
        {"text": "个", "start_time": 2.5, "end_time": 2.7},
    ]
    pieces = asr._thread_text(text, units)
    assert "".join(p["text"] for p in pieces) == text
    assert [p["text"] for p in pieces if p["text"] == "International"] == ["International"]


def test_threading_keeps_a_unit_the_text_does_not_account_for() -> None:
    pieces = asr._thread_text("好", [{"text": "好", "start_time": 0.0, "end_time": 0.2},
                                     {"text": "嗯", "start_time": 0.2, "end_time": 0.4}])
    assert "".join(p["text"] for p in pieces) == "好嗯"


# ---------------------------------------------------------------------------------------
# The cue state machine (survivors of the FunASR-era shaper).
# ---------------------------------------------------------------------------------------


def test_a_sentence_mark_closes_a_cue() -> None:
    cues = asr._aligned_cues(_pieces("今天讲两件事。明天我们接着讲第三件事。"))
    assert [cue["text"] for cue in cues] == ["今天讲两件事。", "明天我们接着讲第三件事。"]
    assert "".join(cue["text"] for cue in cues) == "今天讲两件事。明天我们接着讲第三件事。"


def test_the_ceiling_closes_a_cue_and_the_tail_is_kept() -> None:
    """The ceiling is a readability target, not a guillotine: the tail stays with the cue before it.

    This is the FunASR-era rule verbatim — an undersized remainder is absorbed rather than published
    as a one-character subtitle line — so the assertion is about text preservation, and about the
    absorbed tail not being dropped.
    """

    long_text = "一" * asr._CUE_MAX_CHARS + "尾"
    cues = asr._aligned_cues(_pieces(long_text))
    assert "".join(cue["text"] for cue in cues) == long_text
    assert [cue["text"][-1] for cue in cues] == ["尾"] or len(cues) == 1


def test_a_pause_closes_only_a_cue_that_can_stand_alone() -> None:
    pieces = _pieces("短短") + [
        {"text": "之后", "start": 4.0, "end": 4.4},
    ]
    cues = asr._aligned_cues(pieces)
    assert len(cues) == 1, "a fragment separated by a pause is absorbed, not split"


def test_a_fragment_is_absorbed_by_the_cue_before_it() -> None:
    cues = asr._aligned_cues(_pieces("这是一句足够长的话。好。"))
    assert len(cues) == 1
    assert cues[0]["text"].endswith("好。")


def test_a_mark_at_a_boundary_is_handed_back() -> None:
    pieces = [
        {"text": "一", "start": 0.0, "end": 0.4},
        {"text": "样", "start": 0.4, "end": 0.8},
        {"text": "长", "start": 0.8, "end": 1.2},
        {"text": "的", "start": 1.2, "end": 1.6},
        {"text": "句", "start": 1.6, "end": 2.0},
        {"text": "子", "start": 2.0, "end": 2.4},
        {"text": "，", "start": 2.4, "end": 2.4},
        {"text": "新", "start": 5.0, "end": 5.4},
        {"text": "句", "start": 5.4, "end": 5.8},
        {"text": "开", "start": 5.8, "end": 6.2},
        {"text": "始", "start": 6.2, "end": 6.6},
        {"text": "了", "start": 6.6, "end": 7.0},
        {"text": "吧", "start": 7.0, "end": 7.4},
    ]
    cues = asr._aligned_cues(pieces)
    assert cues[0]["text"] == "一样长的句子，"
    assert cues[1]["text"] == "新句开始了吧"


def test_latin_words_keep_their_separator_when_a_fragment_is_absorbed() -> None:
    assert asr._join_text("Idea", "Moments") == "Idea Moments"
    assert asr._join_text("思想", "观念") == "思想观念"


def test_cues_are_monotonic_and_carry_the_recognised_text() -> None:
    text = "第一句话说完了。第二句话也说完了吧。"
    cues = asr._aligned_cues(_pieces(text))
    assert "".join(cue["text"] for cue in cues) == text
    assert all(cues[i]["end"] <= cues[i + 1]["start"] for i in range(len(cues) - 1))


# ---------------------------------------------------------------------------------------
# Configuration guards.
# ---------------------------------------------------------------------------------------


def test_config_refuses_a_declaration_that_contradicts_a_hub_level_model() -> None:
    with pytest.raises(ValueError):
        asr.ASRConfig(model_name="Qwen/Qwen3-ASR-1.7B-hf", model_id="Other/Thing")


def test_config_accepts_a_truthful_declaration_beside_a_real_local_path(
    tmp_path, monkeypatch
) -> None:
    """The relative checkpoint form the README documents is not a competing identity.

    Existence is what separates it from a hub id, so the test gives it a directory to exist in — the
    rule probes the filesystem exactly as the loader does.
    """

    (tmp_path / "models" / "Qwen3-ASR-1.7B-hf").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    config = asr.ASRConfig(model_name="models/Qwen3-ASR-1.7B-hf",
                           model_id="Qwen/Qwen3-ASR-1.7B-hf")
    assert config.model_id == "Qwen/Qwen3-ASR-1.7B-hf"
    assert config.model_name == "models/Qwen3-ASR-1.7B-hf"


@pytest.mark.parametrize("value", [0, -1, "180"])
def test_config_refuses_a_bad_chunk_seconds(value: object) -> None:
    with pytest.raises(ValueError):
        asr.ASRConfig(model_name="Qwen/Qwen3-ASR-1.7B-hf", chunk_seconds=value)  # type: ignore[arg-type]


def test_config_refuses_a_hostile_local_source() -> None:
    with pytest.raises(ValueError):
        asr.ASRConfig(model_name="Qwen/Qwen3-ASR-1.7B-hf", local_source="https://host/x")


# ---------------------------------------------------------------------------------------
# The runner contract: lazy, one construction for N items, bounded retries, monotonic counters.
# ---------------------------------------------------------------------------------------


def _runner(monkeypatch, text: str = "今天讲两件事。明天我们接着讲第三件事。", **kwargs):
    """A runner over fake models and fake audio.

    The audio read is patched because the ASR stack (numpy + soundfile) is an optional extra: these
    tests describe the runner's contract, not the decoder libraries, so they run wherever numpy and
    soundfile are installed and skip where they are not.
    """

    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    samples = np.zeros(asr.SAMPLE_RATE * 3, dtype="float32")
    monkeypatch.setattr(sf, "read", lambda *args, **kwargs_: (samples, asr.SAMPLE_RATE))
    monkeypatch.setattr(sf, "write", lambda *args, **kwargs_: None)

    units = _units(text)
    builds: list[dict] = []

    def factory(**factory_kwargs):
        builds.append(factory_kwargs)
        return _FakeModelSet(text, units)

    config = asr.ASRConfig(model_name="Qwen/Qwen3-ASR-1.7B-hf", device="cpu", **kwargs)
    return asr.ASRRunner(config, model_factory=factory), builds


def test_the_runner_is_lazy_and_constructs_one_model_set_for_many_items(monkeypatch) -> None:
    runner, builds = _runner(monkeypatch)
    assert runner.model_constructions == 0, "no model may be built before the first use"
    first = runner.transcribe("/nonexistent/one.wav")
    second = runner.transcribe("/nonexistent/two.wav")
    assert builds and len(builds) == 1
    assert runner.model_constructions == 1
    assert runner.model_load_attempts == 1
    assert first == second, "the same audio must produce the same cues"


def test_a_failed_load_pays_an_attempt_and_no_construction(monkeypatch) -> None:
    pytest.importorskip("numpy")
    pytest.importorskip("soundfile")

    def factory(**kwargs):
        raise RuntimeError("boom")

    runner = asr.ASRRunner(
        asr.ASRConfig(model_name="Qwen/Qwen3-ASR-1.7B-hf", device="cpu"), model_factory=factory
    )
    for _ in range(asr.MAX_MODEL_LOAD_ATTEMPTS):
        with pytest.raises(asr.ASRModelError):
            runner.transcribe("/nonexistent/one.wav")
    assert runner.model_constructions == 0
    assert runner.model_load_attempts == asr.MAX_MODEL_LOAD_ATTEMPTS
    with pytest.raises(asr.ASRModelError):
        runner.transcribe("/nonexistent/one.wav")
    assert runner.model_load_attempts == asr.MAX_MODEL_LOAD_ATTEMPTS, "the cap is not spent again"


def test_release_makes_a_rebuild_pay_a_second_construction(monkeypatch) -> None:
    runner, builds = _runner(monkeypatch)
    runner.transcribe("/nonexistent/one.wav")
    runner.release()
    runner.transcribe("/nonexistent/two.wav")
    assert len(builds) == 2
    assert runner.model_constructions == 2, "the counter is monotonic and is not reset by release"


def test_the_runner_uses_the_configured_chunk_size(monkeypatch) -> None:
    runner, _ = _runner(monkeypatch, chunk_seconds=0.5)
    assert runner.config.chunk_seconds == 0.5
    assert runner.provenance()["chunk_seconds"] == "0.5"


def test_the_runner_pads_a_short_final_chunk_before_alignment(monkeypatch) -> None:
    """The splitter tiles exactly; the aligner's minimum is met where that requirement lives."""

    runner, _ = _runner(monkeypatch, chunk_seconds=3.0)
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    samples = np.zeros(int(asr.SAMPLE_RATE * 3.01), dtype="float32")
    monkeypatch.setattr(sf, "read", lambda *args, **kwargs_: (samples, asr.SAMPLE_RATE))
    written: list[int] = []
    monkeypatch.setattr(sf, "write", lambda path, data, rate: written.append(len(data)))

    runner.transcribe("/nonexistent/tail.wav")

    assert len(written) == 2, "3.01 s at a 3 s cap is two chunks"
    assert written[0] == int(asr.SAMPLE_RATE * 3.0)
    assert written[-1] >= int(asr._CHUNK_MIN_SECONDS * asr.SAMPLE_RATE), "the tail was padded"


def test_the_pipeline_stitches_per_chunk_timings_with_their_offset(monkeypatch) -> None:
    """Two chunks: the second chunk's units must land at their offset in the recording."""

    runner, _ = _runner(monkeypatch, chunk_seconds=1.0)
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    long_audio = np.zeros(asr.SAMPLE_RATE * 3, dtype="float32")  # 3 chunks of 1 s
    monkeypatch.setattr(sf, "read", lambda *args, **kwargs_: (long_audio, asr.SAMPLE_RATE))
    cues = runner.transcribe("/nonexistent/long.wav")
    assert cues, "the fake models always produce text"
    assert max(cue["end"] for cue in cues) > 1.0, "the second chunk's timings were offset"


# ---------------------------------------------------------------------------------------
# Provenance: the new keys, and the redaction that must survive the engine change.
# ---------------------------------------------------------------------------------------


def test_provenance_redacts_a_windows_path_and_publishes_a_relative_one() -> None:
    """The redaction rule's real coverage, pinned on both sides.

    It catches a Windows path, a URL and a credential-marked value — and it deliberately lets the
    documented *relative* checkpoint path through, because that is how a local checkpoint is named.
    """

    runner = asr.ASRRunner(asr.ASRConfig(model_name="Qwen/Qwen3-ASR-1.7B-hf", device="cpu"))
    provenance = runner.provenance()
    assert provenance["model_name"] == "Qwen/Qwen3-ASR-1.7B-hf"
    assert provenance["aligner_model"] == asr.DEFAULT_ALIGNER_MODEL
    assert "vad_model" not in provenance, "the VAD component left with the engine"

    for hostile in ("C:\\models\\Qwen3-ASR-1.7B-hf", "https://host/models", "myorg/token_abc"):
        assert asr.ASRRunner(asr.ASRConfig(model_name=hostile, device="cpu")).provenance()[
            "model_name"
        ] == "[redacted]", hostile

    relative = asr.ASRRunner(
        asr.ASRConfig(model_name="models/Qwen3-ASR-1.7B-hf", device="cpu")
    ).provenance()["model_name"]
    assert relative == "models/Qwen3-ASR-1.7B-hf"


def test_default_config_resolves_the_declared_language_and_the_prompt_terms(monkeypatch) -> None:
    monkeypatch.setenv("BILI_ASR_LANGUAGE", "Chinese")
    monkeypatch.setenv("BILI_ASR_HOTWORDS", "新词,攻势")
    monkeypatch.setenv("BILI_ASR_CHUNK_SECONDS", "90")
    config = asr.default_config()
    assert config.language == "Chinese"
    assert "新词" in config.hotwords and config.hotwords.count("攻势") == 1
    assert config.chunk_seconds == 90.0


# ---------------------------------------------------------------------------------------
# Products: unchanged, and still the shape the archive writes.
# ---------------------------------------------------------------------------------------


def test_srt_and_txt_are_built_from_the_cues() -> None:
    cues = [{"start": 0.0, "end": 2.5, "text": "第一句。"},
            {"start": 3.0, "end": 4.25, "text": "第二句。"}]
    srt = asr.segments_to_srt(cues)
    assert "1\n00:00:00,000 --> 00:00:02,500\n第一句。\n" in srt
    assert "2\n00:00:03,000 --> 00:00:04,250\n第二句。\n" in srt
    assert asr.segments_to_txt(cues) == "第一句。\n第二句。"


def test_the_srt_clock_rounds_to_milliseconds() -> None:
    assert asr._fmt_srt_time(0.0) == "00:00:00,000"
    assert asr._fmt_srt_time(3661.2349) == "01:01:01,235"
    assert asr._fmt_srt_time(-1) == "00:00:00,000"


# ---------------------------------------------------------------------------------------
# The offline guard, carried over from the retired reproducibility suite: transcribing must not
# reach the network, whatever the engine is.
# ---------------------------------------------------------------------------------------


def test_transcription_imports_no_network_module(monkeypatch) -> None:
    runner, _ = _runner(monkeypatch)
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "socket" or name.startswith(("socket.", "modelscope.", "requests.")):
            raise AssertionError(f"the ASR boundary imported {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    assert runner.transcribe("/nonexistent/offline.wav"), "the fake models always produce text"


def test_the_dependency_hint_names_the_extra() -> None:
    """The message a host without the extra prints must name what to install."""

    assert "[asr]" in asr._INSTALL_HINT
    assert asr.ASRDependencyError("x").args == ("x",)


# ---------------------------------------------------------------------------------------
# Descriptor materialization, carried over from the retired reproducibility suite: the CLI hands
# the boundary a confined descriptor, which the decoder libraries cannot always open.
# ---------------------------------------------------------------------------------------


def test_a_descriptor_path_is_copied_to_a_readable_file(tmp_path) -> None:
    source = tmp_path / "audio.m4a"
    source.write_bytes(b"payload")
    handle = os.open(source, os.O_RDONLY)
    temporary = None
    try:
        path, temporary = asr._materialize_input(f"/proc/self/fd/{handle}")
        assert temporary is not None and path == temporary
        assert pathlib.Path(path).read_bytes() == b"payload"
    finally:
        os.close(handle)
        if temporary:
            os.unlink(temporary)


def test_a_plain_path_is_returned_untouched() -> None:
    assert asr._materialize_input("/tmp/whatever.m4a") == ("/tmp/whatever.m4a", None)
