"""Bilibili HTTP client: the only module that opens sockets.

Owns buvid bootstrap (x/frontend/finger/spi), WBI signing (pure functions),
and the risk-control backoff budget (spec asr-archive-cli.md
"HTTP / WBI / risk-control contract"). The HTTP transport is injectable so
tests never touch the network.
"""

from __future__ import annotations

import hashlib
import random
import time
import urllib.parse
from typing import Any, Callable, Mapping, Protocol

API_BASE = "https://api.bilibili.com"

REC_ARCHIVES_URL = API_BASE + "/x/series/recArchivesByKeywords"
FINGER_SPI_URL = API_BASE + "/x/frontend/finger/spi"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)
BASE_HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}

# ---------------------------------------------------------------- WBI signing

# MIXIN_KEY_ENC_TAB from bilibili-API-collect docs/misc/sign/wbi.md
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43,
    5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16,
    24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59,
    6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_WBI_FILTER_CHARS = "!'()*"


def get_mixin_key(img_key: str, sub_key: str) -> str:
    """Reorder img_key+sub_key via the mixin table; keep first 32 chars."""
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_wbi(
    params: Mapping[str, Any],
    img_key: str,
    sub_key: str,
    wts: int | None = None,
) -> dict[str, Any]:
    """Pure WBI signing: (params, img_key, sub_key) -> params + wts/w_rid."""
    if wts is None:
        wts = int(time.time())
    mixin = get_mixin_key(img_key, sub_key)
    signed = dict(params)
    signed["wts"] = wts
    clean = {
        k: "".join(c for c in str(v) if c not in _WBI_FILTER_CHARS)
        for k, v in sorted(signed.items())
    }
    query = urllib.parse.urlencode(clean)
    signed["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return signed


# ------------------------------------------------------- risk classification

RISK_OK = "ok"
RISK_RETRYABLE = "retryable"
RISK_RETRY_ONCE_WBI = "retry_once_wbi"
RISK_GONE = "gone"

_RETRYABLE_CODES = {-412, -352, -799}
_GONE_CODES = {-404, -62002}


def classify_risk(status: int, body: dict[str, Any] | None) -> str:
    """Map (HTTP status, JSON body) to a risk class per spec taxonomy."""
    if status == 412 or status >= 500:
        return RISK_RETRYABLE
    if status == 404:
        return RISK_GONE
    if status != 200:
        # 2xx other than 200 / unexpected 3xx-4xx: retry, bounded by budget
        return RISK_RETRYABLE
    if body is None:
        # HTTP 200 with an unparseable (non-JSON) body: the classic
        # risk-control challenge-page signal (412-adjacent). Retryable
        # within the budget, never RISK_OK (avoids None.get crashes).
        return RISK_RETRYABLE
    code = body.get("code", 0)
    if code == 0:
        return RISK_OK
    if code in _RETRYABLE_CODES:
        return RISK_RETRYABLE
    if code == -403:
        return RISK_RETRY_ONCE_WBI
    if code in _GONE_CODES:
        return RISK_GONE
    # unknown negative codes: not retryable; for page-level enumeration a
    # non-zero unknown code (e.g. -101) ends enumeration of this page
    return RISK_GONE


class RiskBudgetExhausted(Exception):
    """Terminal: retry budget spent on a retryable risk signal."""

    def __init__(self, last_code: int | str, message: str = "") -> None:
        self.last_code = last_code
        super().__init__(
            message or f"risk-control retry budget exhausted (last={last_code})"
        )


# ------------------------------------------------------------------ transport


class Transport(Protocol):
    """Minimal HTTP seam; default impl is requests, tests inject fakes."""

    def get_json(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        cookies: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> tuple[int, dict[str, Any] | None]:
        """Return (HTTP status, parsed JSON body or None)."""
        raise NotImplementedError


class RequestsTransport:
    def __init__(self) -> None:
        import requests  # lazy: tests never import it through this class

        self._session = requests.Session()
        self._session.headers.update(BASE_HEADERS)

    def get_json(self, url, params=None, headers=None, cookies=None, timeout=20.0):
        resp = self._session.get(
            url,
            params=dict(params or {}),
            headers=dict(headers or {}),
            cookies=dict(cookies or {}),
            timeout=timeout,
        )
        body = None
        try:
            body = resp.json()
        except ValueError:
            body = None
        return resp.status_code, body


def build_default_transport() -> Transport:
    return RequestsTransport()


def default_sleeper() -> Callable[[float], None]:
    return time.sleep


# -------------------------------------------------------------------- client


class BiliClient:
    """Bilibili API client with buvid bootstrap and risk backoff."""

    def __init__(
        self,
        transport: Transport | None = None,
        sleeper: Callable[[float], None] | None = None,
        jitter: Callable[[], float] | None = None,
        max_attempts: int = 5,
        backoff_base: float = 2.0,
        backoff_cap: float = 60.0,
    ) -> None:
        self.transport = transport if transport is not None else build_default_transport()
        self._sleeper = sleeper if sleeper is not None else default_sleeper()
        # jitter returns seconds to add; default uniform in [0, 1)
        self._jitter = jitter if jitter is not None else (
            lambda: random.uniform(0.0, 1.0)
        )
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._buvid: dict[str, str] | None = None
        self.last_failed_page: int = 1  # page active when budget exhausted
        # Pages fetched during the most recent fetch_pages call. Alive even
        # after RiskBudgetExhausted/GoneResponse so the CLI can persist the
        # partial merge (H2: honest --resume).
        self.pages_fetched: list[list[dict[str, Any]]] = []

    # -- internals ---------------------------------------------------------

    def _sleep_backoff(self, attempt: int) -> None:
        delay = min(self.backoff_base * (2 ** (attempt - 1)), self.backoff_cap)
        delay += max(0.0, self._jitter())
        self._sleeper(delay)

    def _refresh_buvid(self) -> dict[str, str]:
        try:
            status, body = self.transport.get_json(FINGER_SPI_URL)
        except Exception as exc:  # transport-level error: terminal budget path
            raise RiskBudgetExhausted(exc, "finger/spi bootstrap transport error")
        if status != 200 or not body or body.get("code") != 0:
            raise RiskBudgetExhausted(
                status if status != 200 else (body or {}).get("code", "spi"),
                f"finger/spi bootstrap failed (status={status})",
            )
        data = body.get("data") or {}
        self._buvid = {"buvid3": data.get("b_3", ""), "buvid4": data.get("b_4", "")}
        return self._buvid

    def _ensure_buvid(self, refresh: bool = False) -> dict[str, str]:
        if refresh or self._buvid is None:
            return self._refresh_buvid()
        return self._buvid

    def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET with risk backoff; returns the JSON body on RISK_OK."""
        cookies = self._ensure_buvid()
        refreshed = False  # buvid refreshed once per request budget
        last_code: int | str = 0
        for attempt in range(1, self.max_attempts + 1):
            try:
                status, body = self.transport.get_json(
                    url, params=params, headers=BASE_HEADERS, cookies=cookies
                )
            except Exception as exc:
                # H1: transport errors (requests.Timeout/ConnectionError/DNS,
                # or any injected transport failure) are retryable within the
                # same risk budget instead of crashing with a traceback.
                last_code = exc
                if attempt >= self.max_attempts:
                    break
                self._sleep_backoff(attempt)
                continue
            risk = classify_risk(status, body)
            if risk == RISK_OK:
                return body
            last_code = (
                "200-non-json" if (status == 200 and body is None)
                else status if status != 200
                else body.get("code", status)
            )
            if risk in (RISK_RETRYABLE, RISK_RETRY_ONCE_WBI):
                if attempt >= self.max_attempts:
                    break
                self._sleep_backoff(attempt)
                if risk == RISK_RETRYABLE and not refreshed:
                    # refresh buvid once mid-sequence
                    cookies = self._ensure_buvid(refresh=True)
                    refreshed = True
                # simplify: WBI retry-once needs mixin re-derive; this client
                # targets the no-WBI fallback endpoint, so -403 just re-sends.
                continue
            # RISK_GONE or unclassified terminal: propagate as gone marker
            raise _GoneResponse(last_code)
        raise RiskBudgetExhausted(last_code)

    # -- public API --------------------------------------------------------

    def fetch_pages(
        self, mid: int, max_pages: int | None = None
    ) -> list[list[dict[str, Any]]]:
        """Enumerate archive pages via recArchivesByKeywords.

        Returns a list of per-page archive lists (new/dupe mix preserved).
        Raises RiskBudgetExhausted when the retry budget runs out mid-page.
        Stops on: empty page streak (2), or reaching api total, or max_pages.
        """
        pages: list[list[dict[str, Any]]] = []
        seen: set[str] = set()
        total: int | None = None
        empty_streak = 0
        pn = 1
        self.pages_fetched = pages
        while True:
            self.last_failed_page = pn
            body = self._request(
                REC_ARCHIVES_URL,
                {"mid": mid, "keywords": "", "ps": 30, "pn": pn},
            )
            data = body.get("data") or {}
            page_info = data.get("page") or {}
            total = page_info.get("total", total)
            arcs = data.get("archives") or []
            if not arcs:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
                pages.append(arcs)
                seen.update(a.get("bvid") for a in arcs if a.get("bvid"))
            pn += 1
            if max_pages is not None and pn > max_pages:
                break
            if total is not None and total > 0 and len(seen) >= total:
                break
            # Inter-page pacing: real randomized delay (0.8-1.6s like the
            # retired script) through the jitter seam, to avoid triggering
            # 412 risk-control from back-to-back page requests.
            self._sleeper(0.8 + max(0.0, self._jitter()) * 0.8)
        return pages

    def merge_pages(
        self, pages: list[list[dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        """Dedupe archive dicts across pages into bvid -> meta record."""
        records: dict[str, dict[str, Any]] = {}
        for arcs in pages:
            for a in arcs:
                bvid = a.get("bvid")
                if not bvid or bvid in records:
                    continue
                records[bvid] = {
                    "bvid": bvid,
                    "aid": a.get("aid"),
                    "title": (a.get("title") or "").strip(),
                    "duration_s": a.get("duration", 0),
                    "pubdate": a.get("pubdate"),
                }
        return records


class _GoneResponse(Exception):
    """Internal: terminal 404/gone signal at page level."""

    def __init__(self, code: int | str) -> None:
        self.code = code
        super().__init__(f"terminal gone response (code={code})")


# public alias for callers (cli) catching page-level terminal responses
GoneResponse = _GoneResponse
