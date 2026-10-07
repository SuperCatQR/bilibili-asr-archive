# Reference extracts

Two sections copied out of the upstream
[`SocialSisterYi/bilibili-API-collect`](https://github.com/SocialSisterYi/bilibili-API-collect)
documentation because the product's behaviour is defined against them. The
upstream repository is no longer distributed, so these extracts are the copy of
record. They are **reference material, not product code** — nothing under
`src/`, `tests/` or `scripts/` reads them; they are here for a human checking why
a field is handled the way it is.

| File | What it pins |
|---|---|
| [player.md](bilibili-API-collect/player.md) | The player endpoint and its parameters — the shape `probe-subs` and `download-audio` request against. |
| [risk-and-stream.md](bilibili-API-collect/risk-and-stream.md) | Risk-control responses and the audio quality-ID table (`30216`=64K, `30232`=132K, `30280`=192K, `30250`=Dolby, `30251`=Hi-Res), including the reason `30232` must not be read as FLAC. |

These extracts preserve the archived API contract decisions. They were
flattened from the upstream `docs/video/` and `docs/misc/` layout on
2026-09-25, which is why the citations above carry no `docs/` segment.
