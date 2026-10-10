"""Model execution port; workflow ownership and process lifetime stay outside it."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class BackendCapabilities:
    name: str
    precisions: tuple[str, ...]
    native_asr_batch: bool
    native_alignment_batch: bool
    cancellation_scope: str
    quantization_scopes: tuple[str, ...] = ()

    def evidence(self) -> dict:
        return asdict(self)


class InferenceBackend(Protocol):
    capabilities: BackendCapabilities

    def generate(self, model: Any, inputs: Any, *, max_new_tokens: int,
                 disable_cache: bool) -> Any: ...

    def align(self, model: Any, inputs: Any) -> Any: ...


class HuggingFaceBackend:
    """Execute native Transformers calls in the existing task-owned process.

    This adapter does not own jobs, leases, retries, output commits, a second
    queue, or a shared engine. Aborting it means terminating its owned session;
    a future shared service must implement per-request abort before advertising
    a different cancellation scope.
    """

    capabilities = BackendCapabilities("huggingface", ("bfloat16", "float16"), True, True, "owned_process")

    def generate(self, model: Any, inputs: Any, *, max_new_tokens: int,
                 disable_cache: bool) -> Any:
        return model.generate(**inputs, max_new_tokens=max_new_tokens,
                              **({"use_cache": False} if disable_cache else {}))

    def align(self, model: Any, inputs: Any) -> Any:
        return model(**inputs).logits
