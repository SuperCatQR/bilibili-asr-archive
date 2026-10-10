"""DeepSeek Flash JSON adapter. No durable state or implicit HTTP retries."""

from __future__ import annotations

import json
import os
from typing import Any

import requests

from bili_asr.editorial import EditorialConfig, SYSTEM_PROMPT, canonical


class DeepSeekError(RuntimeError):
    pass


def request_body(chunk: dict[str, Any], config: EditorialConfig, *, system_prompt: str = SYSTEM_PROMPT) -> dict[str, Any]:
    return {"model": config.model, "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": canonical(chunk)}],
        "response_format": {"type": "json_object"}, "stream": False,
        "thinking": {"type": "enabled", "reasoning_effort": config.reasoning_effort},
        "top_p": config.top_p,
        "max_tokens": config.max_output_tokens}


class DeepSeekClient:
    def __init__(self, api_key: str | None = None, *, session: requests.Session | None = None):
        self.api_key = api_key if api_key is not None else os.environ.get("DEEPSEEK_API_KEY", "")
        self.session = session or requests.Session()
        self._owns_session = session is None

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def complete(self, request: dict[str, Any], config: EditorialConfig) -> dict[str, Any]:
        if not self.api_key.strip():
            raise DeepSeekError("DEEPSEEK_API_KEY is not configured")
        try:
            response = self.session.post(
                config.base_url + "/chat/completions", json=request,
                headers={"Authorization": "Bearer " + self.api_key},
                timeout=(30, config.timeout_seconds), allow_redirects=False)
        except requests.RequestException:
            # Exception strings can include request details. Keep them out of
            # logs, durable attempt records and CLI diagnostics.
            raise DeepSeekError("DeepSeek transport failed") from None
        if response.status_code != 200:
            raise DeepSeekError(f"DeepSeek HTTP {response.status_code}")
        try:
            value = response.json()
        except ValueError:
            raise DeepSeekError("DeepSeek returned non-JSON HTTP content") from None
        if not isinstance(value, dict):
            raise DeepSeekError("DeepSeek returned an invalid envelope")
        return value


def parse_response(envelope: dict[str, Any]) -> Any:
    try:
        choice = envelope["choices"][0]
        if choice["finish_reason"] != "stop":
            error = DeepSeekError("DeepSeek output is truncated or unfinished")
            usage = envelope.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            details = usage.get("completion_tokens_details")
            details = details if isinstance(details, dict) else {}
            numbers = {"prompt_tokens": usage.get("prompt_tokens"),
                       "completion_tokens": usage.get("completion_tokens"),
                       "reasoning_tokens": details.get("reasoning_tokens")}
            error.safe_details = {key: value for key, value in numbers.items()
                                  if type(value) is int and 0 <= value < 2**63}
            error.safe_details["length_exceeded"] = choice["finish_reason"] == "length"
            message = choice.get("message")
            message = message if isinstance(message, dict) else {}
            for name, field in (("output_chars", "content"), ("reasoning_chars", "reasoning_content")):
                value = message.get(field)
                error.safe_details[name] = len(value) if isinstance(value, str) else 0
            raise error
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekError("DeepSeek output is empty")

        def object_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON field")
                result[key] = value
            return result

        return json.loads(content, object_pairs_hook=object_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (KeyError, IndexError, TypeError, ValueError):
        raise DeepSeekError("DeepSeek output is not a valid JSON revision") from None
