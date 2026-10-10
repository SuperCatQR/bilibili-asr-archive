"""Public, field-limited evidence rules shared by storage and export readers."""
from __future__ import annotations

from bili_asr.canonical_json import digest
from bili_asr.source_metadata import valid_source_text

from bili_asr.contracts.registry import SOURCE_SUPPLEMENT_POLICY as POLICY
KIND = "archive-part-projection"
FIELDS = {"version", "platform", "externalVideoId", "partIndex", "videoPartId",
          "cid", "field", "value", "sourceKind", "observedAt"}


def validate_supplement(value: object, metadata: dict, part_id: int) -> dict:
    """Verify identity and value binding, not an upstream digital signature.

    The trusted recorder reads the archive itself; caller-authored evidence is
    never accepted by apply. Acquisition time in this historical projection is
    unknown, independently of the time the evidence is registered.
    """
    if not isinstance(value, dict) or set(value) != {"supplementId", "evidence"}:
        raise ValueError("source-supplement: invalid public evidence envelope")
    evidence = value["evidence"]
    if (not isinstance(evidence, dict) or set(evidence) != FIELDS
            or type(evidence["version"]) is not int or evidence["version"] != 1
            or evidence["sourceKind"] != KIND or evidence["observedAt"] is not None
            or evidence["field"] != "partTitle" or evidence["platform"] != "bilibili"
            or value["supplementId"] != digest(evidence)):
        raise ValueError("source-supplement: unsupported or altered evidence")
    for field, minimum in (("partIndex", 0), ("videoPartId", 1), ("cid", 1)):
        if type(evidence[field]) is not int or not minimum <= evidence[field] <= 2**53 - 1:
            raise ValueError("source-supplement: invalid part identity")
    if (any(evidence[field] != metadata[field] for field in ("platform", "externalVideoId", "partIndex"))
            or evidence["videoPartId"] != part_id
            or not valid_source_text(evidence["value"], limit=512) or not evidence["value"].strip()
            or evidence["value"] != metadata["partTitle"]):
        raise ValueError("source-supplement: source or title binding mismatch")
    return evidence
