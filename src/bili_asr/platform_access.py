"""Require explicit access and processing evidence before live Bilibili calls."""
import os
import re


class PlatformAccessError(ValueError):
    """Live network acquisition is disabled until its basis is recorded."""


def require_platform_access() -> None:
    # Opaque references only: no credential, signed URL or correspondence in logs.
    for name in ('BILI_PLATFORM_ACCESS_REFERENCE', 'BILI_CONTENT_PROCESSING_REFERENCE'):
        value = os.environ.get(name, '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', value):
            raise PlatformAccessError(
                f'platform-access: live Bilibili acquisition disabled; record actual authorization in {name}'
            )
