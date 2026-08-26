"""Model-provider boundary for live and fake Responses-style agent loops."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

OPENAI_REQUEST_TIMEOUT_SECONDS = 90.0
OPENAI_MAX_RETRIES = 1


@dataclass(frozen=True)
class ProviderToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str
    purpose: str = ""


@dataclass(frozen=True)
class ProviderResult:
    response_id: str
    tool_calls: list[ProviderToolCall] = field(default_factory=list)
    final: Optional[dict[str, Any]] = None
    message: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: int = 0


class ModelProvider(Protocol):
    provider_name: str
    model: str

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any],
    ) -> ProviderResult:
        """Return either tool calls or a structured final result."""


class FakeModelProvider:
    """Deterministic provider for unit/API tests.

    Each queued item is returned as one model response. This mirrors the
    Responses loop without making network calls or giving tests hidden evidence.
    """

    provider_name = "fake"

    def __init__(self, responses: list[ProviderResult], model: str = "fake-responses-model"):
        self.responses = list(responses)
        self.model = model
        self.requests: list[dict[str, Any]] = []

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any],
    ) -> ProviderResult:
        self.requests.append(
            {
                "instructions": instructions,
                "input_items": input_items,
                "tools": tools,
                "response_format": response_format,
            }
        )
        if not self.responses:
            raise RuntimeError("Fake model provider has no queued response.")
        return self.responses.pop(0)


class OpenAIResponsesProvider:
    """OpenAI Responses API adapter.

    The import is intentionally lazy so default tests do not require credentials
    or instantiate the network client.
    """

    provider_name = "openai"

    def __init__(self, model: Optional[str] = None, client: Optional[Any] = None):
        selected_model = model or os.environ.get("OPENAI_MODEL")
        if not selected_model:
            raise RuntimeError("OPENAI_MODEL is required for live model execution.")
        self.model = selected_model
        self._conversation_items: list[dict[str, Any]] = []
        self._submitted_input_count = 0
        if client is not None:
            self._client = client
            return

        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for live model execution.")

        from openai import OpenAI  # type: ignore[import-not-found]

        self._client = OpenAI(
            timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
            max_retries=OPENAI_MAX_RETRIES,
        )

    def respond(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any],
    ) -> ProviderResult:
        started = time.perf_counter()
        new_input_items = input_items[self._submitted_input_count :]
        request: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": [*self._conversation_items, *new_input_items],
            "tools": tools,
            "text": {"format": response_format},
            "include": ["reasoning.encrypted_content"],
            "store": False,
        }
        response = self._client.responses.create(**request)
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = _parse_openai_response(response, latency_ms)
        self._conversation_items.extend(new_input_items)
        self._conversation_items.extend(_response_input_items(response))
        self._submitted_input_count = len(input_items)
        return result


def _response_input_items(response: Any) -> list[dict[str, Any]]:
    """Preserve model output for stateless and Zero Data Retention turns."""
    return [_jsonable_item(item) for item in list(getattr(response, "output", []) or [])]


def _jsonable_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    model_dump = getattr(item, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump(mode="json", exclude_none=True))
    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if hasattr(item, "__dict__"):
        return {
            key: value
            for key, value in vars(item).items()
            if not key.startswith("_") and value is not None
        }
    raise TypeError(f"Unsupported provider output item: {type(item).__name__}")


def _parse_openai_response(response: Any, latency_ms: int) -> ProviderResult:
    output_items = list(getattr(response, "output", []) or [])
    tool_calls: list[ProviderToolCall] = []
    for item in output_items:
        item_type = _get(item, "type")
        if item_type not in {"function_call", "tool_call"}:
            continue
        name = str(_get(item, "name") or _get(item, "function_name") or "")
        raw_arguments = _get(item, "arguments") or "{}"
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
        purpose = str(arguments.pop("purpose", "") if "purpose" in arguments else "")
        tool_calls.append(
            ProviderToolCall(
                name=name,
                arguments=arguments,
                call_id=str(_get(item, "call_id") or _get(item, "id") or name),
                purpose=purpose,
            )
        )

    usage = getattr(response, "usage", None)
    if tool_calls:
        return ProviderResult(
            response_id=str(getattr(response, "id", "")),
            tool_calls=tool_calls,
            input_tokens=_get(usage, "input_tokens"),
            output_tokens=_get(usage, "output_tokens"),
            latency_ms=latency_ms,
        )

    text = getattr(response, "output_text", None) or _message_text(output_items)
    final = json.loads(text) if text else None
    return ProviderResult(
        response_id=str(getattr(response, "id", "")),
        final=final,
        message=text,
        input_tokens=_get(usage, "input_tokens"),
        output_tokens=_get(usage, "output_tokens"),
        latency_ms=latency_ms,
    )


def _message_text(output_items: list[Any]) -> str:
    parts: list[str] = []
    for item in output_items:
        for content in list(_get(item, "content") or []):
            text = _get(content, "text")
            if text:
                parts.append(str(text))
    return "\n".join(parts)


def _get(value: Any, key: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)
