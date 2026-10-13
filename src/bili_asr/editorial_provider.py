"""One endpoint-to-credential policy for execution and offline readiness."""
from dataclasses import dataclass


@dataclass(frozen=True)
class EditorialProvider:
    name: str
    credential_name: str
    opencode_session: bool = False


_PROVIDERS = {
    "https://api.deepseek.com": EditorialProvider("deepseek", "DEEPSEEK_API_KEY"),
    "https://opencode.ai/zen/go/v1": EditorialProvider("opencode", "OPENCODE_API_KEY", True),
}
CREDENTIAL_NAMES = frozenset(policy.credential_name for policy in _PROVIDERS.values())


def editorial_provider(base_url: str) -> EditorialProvider:
    try:
        return _PROVIDERS[base_url.rstrip("/")]
    except (KeyError, AttributeError):
        raise ValueError("unsupported editorial API endpoint") from None
