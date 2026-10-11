"""Configuration for the SQLite-backed metadata commands.

``fetch-meta`` resolves its settings through :func:`load_metadata_config`
so the command layer only composes validated values, and so every display
or debug path that could show the credential instead shows a redacted
presence label.  The SESSDATA value is resolved from ``--sessdata`` or the
``BILI_SESSDATA`` environment variable, is never echoed, logged,
persisted, or rendered by any helper here.  The proxy the gateway applies
to the pinned package is resolved here as well (:func:`resolve_proxy`),
from the constructor argument or ``BILI_HTTP_PROXY`` and the conventional
host variables.  ``status`` and ``runs`` take no credential and no page
arguments; they share only the database-name constant below.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

#: Bilibili user collected by default (未明子).
DEFAULT_MID = 23191782

#: Documented default bound for full-collection runs (carry item C1).
#:
#: ``--limit-pages`` defaults to this instead of unbounded: a full
#: collection without an explicit bound would otherwise only terminate on
#: an upstream empty page, exposing every run to unbounded anti-bot risk.
#: Ten pages at the ingestor's page size of 30 (300 videos) is a resumable,
#: conservative slice; operators opt into longer batches explicitly.
DEFAULT_PAGE_LIMIT = 10

#: Environment variable carrying the optional SESSDATA credential.
SESSDATA_ENV_VAR = "BILI_SESSDATA"

#: Documented operator knob for the HTTP proxy the gateway applies to the
#: pinned package.  The pinned client otherwise forces ``proxies={"all": ""}``
#: and ignores the environment, so a proxied host needs this set.
PROXY_ENV_VAR = "BILI_HTTP_PROXY"

#: Proxy variables in locked precedence order: the documented knob first, then
#: the conventional host variables (the upper-case spelling of each pair
#: first).  A host that already exports ``HTTPS_PROXY`` therefore needs no
#: application change.
PROXY_ENV_VARS = (
    PROXY_ENV_VAR,
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
)

#: File name of the fresh SQLite database below the archive root.  Must
#: stay identical to the storage layer's archive database name because the
#: read commands check for its existence before opening it.
ARCHIVE_DATABASE_NAME = "archive.db"

#: Presence labels used wherever configuration display would show SESSDATA.
SESSDATA_PRESENT_LABEL = "present"
SESSDATA_ABSENT_LABEL = "absent"


class MetadataConfigError(ValueError):
    """A metadata command received an invalid configuration value."""


@dataclass(frozen=True)
class MetadataConfig:
    """Resolved settings for one metadata command invocation.

    ``sessdata`` is excluded from the repr so any accidental debug or
    traceback rendering of the configuration can never carry the value;
    display paths use :func:`redact_sessdata` explicitly.
    """

    mid: int
    archive_root: str
    start_page: int | None
    page_limit: int | None
    resume: bool
    skip_failed_page: bool
    sessdata: str | None = field(repr=False)
    page_retries: int = 0
    operation_retries: int = 0
    incremental: bool = False
    refresh_mode: str = "force"
    ttl_seconds: int = 86400


def load_metadata_config(args: argparse.Namespace) -> MetadataConfig:
    """Validate parsed arguments and environment into a metadata config.

    Page arguments must be positive integers, ``--resume`` and
    ``--start-page`` are mutually exclusive, and an omitted
    ``--limit-pages`` keeps the documented :data:`DEFAULT_PAGE_LIMIT` bound
    so a full-collection run always terminates on a bounded slice (C1).
    Raises :class:`MetadataConfigError` (a ``ValueError``) for any
    violation, which the command maps to the usage-error exit.
    """

    mid = args.mid
    start_page = args.start_page
    page_limit = args.limit_pages
    resume = bool(args.resume)
    skip_failed_page = bool(getattr(args, "skip_failed_page", False))
    page_retries = getattr(args, "page_retries", 0)
    operation_retries = getattr(args, "operation_retries", 0)
    incremental = bool(getattr(args, "incremental", False))
    refresh_mode = getattr(args, "refresh_mode", "force")
    ttl_seconds = getattr(args, "ttl_seconds", 86400)
    if incremental and (resume or start_page is not None):
        raise MetadataConfigError("--incremental cannot be combined with --resume or --start-page")
    if refresh_mode not in {"new", "missing", "stale", "force"} or type(ttl_seconds) is not int or ttl_seconds < 0:
        raise MetadataConfigError("invalid metadata refresh mode or TTL")

    if isinstance(mid, bool) or not isinstance(mid, int) or mid < 1:
        raise MetadataConfigError("--mid must be a positive integer")
    if start_page is not None and (
        isinstance(start_page, bool) or not isinstance(start_page, int) or start_page < 1
    ):
        raise MetadataConfigError("--start-page must be a positive integer")
    if page_limit is not None and (
        isinstance(page_limit, bool) or not isinstance(page_limit, int) or page_limit < 1
    ):
        raise MetadataConfigError("--limit-pages must be a positive integer")
    if resume and start_page is not None:
        raise MetadataConfigError("--resume and --start-page are mutually exclusive")
    if (
        isinstance(page_retries, bool)
        or not isinstance(page_retries, int)
        or not 0 <= page_retries <= 5
    ):
        raise MetadataConfigError("--page-retries must be an integer between 0 and 5")
    if page_limit is None:
        page_limit = DEFAULT_PAGE_LIMIT
    if type(operation_retries) is not int or not 0 <= operation_retries <= 5:
        raise MetadataConfigError("--operation-retries must be an integer between 0 and 5")

    return MetadataConfig(
        mid=mid,
        archive_root=args.archive_root,
        start_page=start_page,
        page_limit=page_limit,
        resume=resume,
        skip_failed_page=skip_failed_page,
        page_retries=page_retries,
        operation_retries=operation_retries,
        incremental=incremental, refresh_mode=refresh_mode, ttl_seconds=ttl_seconds,
        sessdata=resolve_sessdata(
            getattr(args, "sessdata", None), os.environ.get(SESSDATA_ENV_VAR)
        ),
    )


def resolve_sessdata(
    flag_value: str | None, environment_value: str | None = None
) -> str | None:
    """Return the credential from the flag, else the environment, else None.

    The value is resolved for gateway construction only and is never
    echoed.  An explicitly blank flag (``""``) forces anonymous access and
    never falls through to the environment; a blank environment value
    likewise resolves to no credential.
    """

    if flag_value is not None:
        return flag_value or None
    return environment_value or None


def redact_sessdata(sessdata: str | None) -> str:
    """Render SESSDATA presence for any display or debug path.

    Only presence is shown — the credential value itself never appears in
    output, logs, errors, or persisted rows (C6).
    """

    return SESSDATA_PRESENT_LABEL if sessdata else SESSDATA_ABSENT_LABEL


def resolve_proxy(
    argument_value: str | None, environ: Mapping[str, str]
) -> str | None:
    """Return the proxy from the argument, else the environment, else None.

    The resolution order is locked: the explicit argument first, then
    :data:`PROXY_ENV_VARS` in the order declared there.  A blank or
    whitespace-only value counts as unset and never blocks the next level, so
    an empty environment entry cannot silently disable a proxy a
    lower-precedence variable provides; surrounding whitespace is stripped
    from the value that is returned.  When nothing resolves the caller must
    leave the library's own proxy behaviour untouched.
    """

    candidates = (argument_value, *(environ.get(name) for name in PROXY_ENV_VARS))
    for candidate in candidates:
        if candidate is None:
            continue
        value = candidate.strip()
        if value:
            return value
    return None


__all__ = [
    "ARCHIVE_DATABASE_NAME",
    "DEFAULT_MID",
    "DEFAULT_PAGE_LIMIT",
    "PROXY_ENV_VAR",
    "PROXY_ENV_VARS",
    "SESSDATA_ABSENT_LABEL",
    "SESSDATA_ENV_VAR",
    "SESSDATA_PRESENT_LABEL",
    "MetadataConfig",
    "MetadataConfigError",
    "load_metadata_config",
    "redact_sessdata",
    "resolve_proxy",
    "resolve_sessdata",
]
