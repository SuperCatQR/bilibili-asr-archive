# Spike notes: `x/player/wbi/v2` auth tiers (player/wbi/v2 + WBI)

- **Date:** 2026-08-23 · **Plan:** 002-subtitle-audio Task 1 · **Method:** throwaway Python `requests` probes (`.tmp/spike_t1.py`, `.tmp/spike_t2.py`, not committed), run from a CN residential IP (Nanjing, per `ip_info` echo)
- **Sample:** UP 未明子 (mid 23191782), 6 videos across pages 1–3 of `recArchivesByKeywords`: `BV1mk8W6dEyx` (4087s, newest), plus 5 shortest across pages 1–3 (`BV1wLTP6NE9h` 449s, `BV132XgBjER4` 500s, `BV1aRTA6mEGF` 571s, `BV1FPf2BVEu6` 663s, `BV1mk8W6dEyx` 4087s)
- **WBI keys observed (live nav):** `img_key=7cd084941338484aae1ad9425b84077c`, `sub_key=4932caff0ff746eab6f01bf08b70ac45` → derived mixin_key `ea1db124af3c7062474693fa704f4ff8` via the existing `MIXIN_KEY_ENC_TAB` permutation (`bili_client.get_mixin_key` logic re-implemented in the probe — same result). Keys were **stable across both probe runs** (~30 min apart); no rotation observed in-session.

## Auth tier results (subtitle list presence)

| Tier | HTTP | code | `subtitle.subtitles` | Notes |
|---|---|---|---|---|
| No cookie (WBI-signed) | 200 | 0 | **empty** | accepted; `need_login_subtitle: true` in response |
| buvid3+buvid4 only (finger/spi), WBI-signed | 200 | 0 | **empty** | same; `need_login_subtitle: true` |
| buvid only, **unsigned** (no `w_rid`) | 200 | 0 | **empty** | server tolerated unsigned call with buvid cookie (see below) |
| SESSDATA | — | — | **UNTESTED** | no `SESSDATA`/`BILI_SESSDATA` in env; per assignment this tier is documented as untested. Do **not** invent it. |

All 6 sampled videos (incl. the 5 shortest, most likely to carry CC): `sub_count = 0` at every tested tier.

## Key live findings

1. **`need_login_subtitle: true`** appears in the `data` payload at no-cookie and buvid tiers. This is the server explicitly stating subtitle payload requires login — the strongest direct evidence for **Path A expectation confirmed**: no-cookie/buvid `player/wbi/v2` returns an empty AI/CC subtitle list, and the pipeline must fall back to `needs_audio` → audio download → local ASR.
2. **Signature enforcement is lax on this endpoint (today):** an unsigned call (`aid`+`cid`, no `wts`/`w_rid`, buvid cookie present) returned `code 0` with full data, not `-403`. So a signature bug would currently be *silent* — WBI signing correctness must be guarded by the golden-vector unit test, not by live-server rejection. Keep signing per spec regardless.
3. **Response shape (observed):** `data.subtitle.subtitles` = `[]`, `data.subtitle.allow_submit=false`, `data.last_subtitle` absent, `data.view_points=[]`, plus `login_mid: 0`, `vip.status: 0` confirming anonymous identity. With SESSDATA (untested tier) community references expect `subtitles[]` entries with `lan`, `lan_doc`, `subtitle_url` (signed, short-lived), and `ai_status`/`ai_type` fields on AI-generated entries.
4. **`cid` acquisition:** `x/player/pagelist?bvid=...` works at the buvid tier (`code 0`, `data[0].cid`); 未明子 videos are single-P so far.
5. **WBI keys source:** `x/web-interface/nav` returns keys even at `code -101` (not logged in) — `data.wbi_img` is populated regardless of login. `isLogin:false` from nav is a cheap session probe for Path B wiring later.

## Risk-control behavior (412 / -352)

- First enumeration call in probe 1 hit **HTTP 412** (empty body) on a fresh session with a fresh buvid, exactly the pattern the spec's backoff contract describes.
- With exponential backoff (base 2s, cap 30s in probe, 5 attempts, buvid refresh once mid-sequence), enumeration pages succeeded on attempts **2, 2, 3, 4** across four page fetches. **Conclusion: the spec backoff budget (base 2s, cap 60s, max 5 attempts, jitter, one mid-sequence buvid refresh) is adequate** — but attempt counts of 3–4 mean the budget has little headroom; inter-page pacing (~0.8–1.6s) as implemented in `BiliClient.fetch_pages` should be kept, and player-probe calls must also be paced (probe used 3s between videos).
- No `-352` or `-799` observed in this session; classification remains per spec taxonomy (both retryable).

## Decision (feeds Task 2)

**Path A expectation CONFIRMED.** No-cookie and buvid-only `x/player/wbi/v2` both return empty subtitle lists with `need_login_subtitle: true`; the harvest layer (Task 2) should treat `subtitles == []` as `needs_audio` without any error, exactly per spec state machine `sub_checked → needs_audio`. SESSDATA tier remains untested live; Task 2 should still implement optional `BILI_SESSDATA` injection (Path B) behind the same probe, guarded so its absence is the normal, tested path. WBI signing should be implemented per reference vectors (server currently tolerates unsigned calls — do not rely on that).
