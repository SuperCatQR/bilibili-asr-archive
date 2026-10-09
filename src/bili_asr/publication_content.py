"""Pure frozen publication content and writer template contracts."""
from __future__ import annotations

from typing import Any

from bili_asr.manuscript_templates import PUBLISH_RENDERERS, renderer_for
from bili_asr.bilibili_identity import bilibili_source_url, legacy_bilibili_source_ref

PUBLISH_TEMPLATE_VERSION = "publish-v1"
CONTENT_KEYS = frozenset({"title", "markdown", "summary", "tags", "source", "attribution", "editorNote"})
EDITABLE_METADATA = CONTENT_KEYS - {"markdown", "source"}


def normalize_text(value: Any, name: str, *, nonempty: bool = False, multiline: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"publication-content: {name} must be text")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"publication-content: {name} must be valid UTF-8 text") from exc
    if "\x00" in value or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"publication-content: {name} contains control characters")
    if not multiline and ("\n" in value or "\t" in value):
        raise ValueError(f"publication-content: {name} must be one line")
    value = value.strip()
    if nonempty and not value:
        raise ValueError(f"publication-content: {name} must not be empty")
    return value


def normalize_actor(actor: str) -> str:
    return normalize_text(actor, "actor", nonempty=True, multiline=False)


def normalize_content(content: dict[str, Any]) -> dict[str, Any]:
    """Normalize the entire reader-visible object before canonical JSON hashing."""
    if not isinstance(content, dict) or set(content) != CONTENT_KEYS:
        raise ValueError("publication-content: reader content fields do not match the contract")
    source = content["source"]
    if not isinstance(source, dict) or set(source) != {"bvid", "pageIndex", "videoPartId", "url"}:
        raise ValueError("publication-content: invalid source fields")
    ref = legacy_bilibili_source_ref({
        **source, "bvid": normalize_text(source["bvid"], "source.bvid", nonempty=True, multiline=False),
    })
    url = bilibili_source_url(ref)
    tags = content["tags"]
    if not isinstance(tags, list):
        raise ValueError("publication-content: tags must be a list")
    tags = [normalize_text(tag, "tag", nonempty=True, multiline=False) for tag in tags]
    if len(tags) != len(set(tags)):
        raise ValueError("publication-content: duplicate tags are forbidden")
    normalized = {
        "title": normalize_text(content["title"], "title", nonempty=True, multiline=False),
        "markdown": normalize_text(content["markdown"], "markdown", nonempty=True) + "\n",
        "summary": normalize_text(content["summary"], "summary"),
        "tags": tags,
        "source": {"bvid": ref.external_video_id, "pageIndex": ref.part_index,
                   "videoPartId": source["videoPartId"], "url": url},
        "attribution": normalize_text(content["attribution"], "attribution", nonempty=True),
        "editorNote": normalize_text(content["editorNote"], "editorNote"),
    }
    return normalized


def content_from_ai(prepared: dict, markdown_text: str) -> dict:
    """Build the complete default edition and review baseline from frozen input."""
    snapshot = prepared["snapshot"]
    metadata = snapshot["metadata"]
    return normalize_content({
        "title": metadata["title"], "markdown": markdown_text,
        "summary": "", "tags": [],
        "source": {"bvid": metadata["bvid"], "pageIndex": metadata["page_index"],
                   "videoPartId": snapshot["video_part_id"],
                   "url": f"https://www.bilibili.com/video/{metadata['bvid']}/?p={metadata['page_index'] + 1}"},
        "attribution": "\u6839\u636e\u89c6\u9891\u8f6c\u5f55\u6574\u7406\uff0c\u7ecf AI "
                       "\u5408\u6210\u3002",
        "editorNote": "",
    })


def render_publication(content: dict[str, Any]) -> bytes:
    """Render the current writer template from normalized reader content."""
    return renderer_for(PUBLISH_RENDERERS, PUBLISH_TEMPLATE_VERSION)(normalize_content(content))
