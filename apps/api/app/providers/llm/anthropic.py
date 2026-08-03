"""Anthropic adapter for vision classification and email drafting."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx

from app.logging import get_logger
from app.providers.base import LLMMessage, LLMResponse

log = get_logger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicLLMProvider:
    """Real LLM adapter. Selected only when ``ANTHROPIC_API_KEY`` is set."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout = timeout

    # -- internals ---------------------------------------------------------

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    def _build(self, text: str, json_schema: dict[str, Any] | None) -> LLMResponse:
        parsed = None
        if json_schema is not None:
            parsed = _extract_json(text)
        return LLMResponse(text=text, provider_name=self.name, model=self.model, parsed=parsed)

    @staticmethod
    def _schema_instruction(json_schema: dict[str, Any] | None) -> str:
        if not json_schema:
            return ""
        return (
            "\n\nRespond with a single JSON object and nothing else. "
            f"It must conform to this JSON schema:\n{json.dumps(json_schema)}"
        )

    # -- protocol ----------------------------------------------------------

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system + self._schema_instruction(json_schema),
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        data = self._post(payload)
        text = "".join(block.get("text", "") for block in data.get("content", []))
        return self._build(text, json_schema)

    def complete_with_image(
        self,
        *,
        system: str,
        prompt: str,
        image_bytes: bytes | None,
        media_type: str = "image/jpeg",
        max_tokens: int = 1024,
        json_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        content: list[dict[str, Any]] = []
        if image_bytes:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system + self._schema_instruction(json_schema),
            "messages": [{"role": "user", "content": content}],
        }
        data = self._post(payload)
        text = "".join(block.get("text", "") for block in data.get("content", []))
        return self._build(text, json_schema)


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of a model response."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("```")[1]
        if stripped.startswith("json"):
            stripped = stripped[4:]
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(stripped[start : end + 1])
    except json.JSONDecodeError:
        log.warning("llm_json_parse_failed", snippet=stripped[:200])
        return None
