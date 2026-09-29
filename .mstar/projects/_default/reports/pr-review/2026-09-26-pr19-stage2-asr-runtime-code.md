---
stage: 2
seat: asr-runtime-code
domain: asr-runtime-code
pr: 19
head: 84e9767146c03977812591a48a991e0fce7de985
diff_base: 9d530cd646e50142cd92789b2494c72806025ffd
---

# Stage 2 evidence — asr-runtime-code (PR #19)

Seat payload, extracted by the main agent. `bilibili-asr-archive/src/bili_asr/asr.py` and the
dependency declarations were opened at HEAD; every runtime claim below was reproduced by the main
agent independently (the seat's own environment could not import `librosa`).

## [BUG-01] The AAC fallback cannot decode AAC under the librosa the project declares and locks

- **Evidence**: `bilibili-asr-archive/src/bili_asr/asr.py:403-406`; `bilibili-asr-archive/pyproject.toml:36`
  (`librosa>=0.10`); `bilibili-asr-archive/uv.lock:763-764` (pins 1.0.0); `bilibili-asr-archive/README.md:143-144`
- **Impact**: the `.m4a` path this PR repairs still fails on an environment built from the repo's own declarations
- **Effort**: S · **Risk**: MED · **Confidence**: HIGH
- **Merge class**: must-fix
- **Fix sketch**: pin `librosa>=0.10,<1` (and refresh `uv.lock`), or decode non-libsndfile containers through an explicit backend

### Main-agent reproduction (the seat could not run this; I did)

| Step | Result |
|---|---|
| `[asr]` extra resolved in a clean venv on the target host | `librosa 1.0.0`, `numpy 2.5.3`, `scipy 1.18.1` |
| librosa 1.0.0 core deps (PyPI metadata) | **no `audioread`**; 0.11.0 has `audioread>=2.1.9` |
| librosa 1.0.0 `core/audio.py` (wheel source) | `__audioread_load` **absent**, 0 `audioread` mentions; `load()` is a bare `__soundfile_load` |
| `sf.read` on a real AAC `.m4a` | `soundfile.LibsndfileError` |
| `librosa.load` on the same file, **1.0.0** | same `LibsndfileError` |
| `asr._read_audio` on the same file, **1.0.0** | re-raises the same `LibsndfileError` |
| `asr._read_audio`, same file, **0.11.0** (repo venv) | `(89088,) rate 44100` — the fallback works |
| `asr._read_audio`, real corpus `.m4a`, 0.11.0 | `(100167680, 2) rate 48000` |
| the 4 new codec tests under 1.0.0 | **4 passed** — the failure is silent |
