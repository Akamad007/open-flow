"""OpenAI-compatible LLM provider — works with OpenAI, Ollama, vLLM, LM Studio."""

import json
import logging
import re
from typing import Any, Optional, Type

import httpx
from pydantic import BaseModel

from app.config import settings
from app.providers.llm.base import LLMProvider

logger = logging.getLogger(__name__)


def _repair_truncated_json(s: str) -> Optional[str]:
    """Repair a JSON string that was cut off by max_tokens.

    Scans the prefix that successfully parses up to the truncation point and
    closes any open string + outstanding brackets so json.loads succeeds.
    The truncated trailing field is typically lost, but sibling fields earlier
    in the object survive — better than a hard failure.
    """
    if not s:
        return None

    in_string = False
    escape = False
    stack: list[str] = []
    last_safe = 0  # index after the last completed key/value or container

    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            last_safe = i + 1
        elif ch == "," and not stack:
            break
        elif ch in ",":
            last_safe = i  # we can drop the trailing comma later

    # Truncate to before the broken last field, then close everything.
    # Walk back to the last complete field-end (`,` or `{`/`[` opener).
    cut = max(last_safe, 0)
    # Trim a trailing comma if any
    trimmed = s[:cut].rstrip().rstrip(",")
    repaired = trimmed + "".join(reversed(stack))
    return repaired if repaired else None


class OpenAICompatibleProvider(LLMProvider):
    """LLM provider using the OpenAI Chat Completions API format."""

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_base = (api_base or settings.llm_api_base).rstrip("/")
        self.model = model or settings.llm_model

        # Resolve API key: explicit arg > secrets-manager > env var fallback
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = self._resolve_api_key()

        self._client = httpx.AsyncClient(
            base_url=self.api_base,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=300.0,
        )

    @staticmethod
    def _resolve_api_key() -> str:
        """Fetch OPENAI_API_KEY from secrets-manager, fallback to env var."""
        from app.utils.secrets_client import get_secret_sync

        # Try secrets-manager first (runtime fetch, in-memory only)
        key = get_secret_sync("OPENAI_API_KEY")
        if key:
            logger.info("API key resolved from secrets-manager (in-memory only)")
            return key

        # Fallback to env var
        if settings.llm_api_key:
            logger.warning("API key from env var fallback (secrets-manager unavailable)")
            return settings.llm_api_key

        logger.error("No API key found — set OPENAI_API_KEY in secrets-manager or LLM_API_KEY in env")
        return ""

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[Type[BaseModel]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }

        if response_format:
            payload["response_format"] = {"type": "json_object"}

        logger.info("LLM request: model=%s tokens=%d", self.model, max_tokens)

        resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        logger.debug("LLM response length: %d chars", len(content))
        return content

    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        # Use OpenAI's native JSON mode + text instruction for reliability
        messages = [
            {"role": "system", "content": system_prompt + "\n\nYou MUST respond with valid JSON only. No markdown fences."},
            {"role": "user", "content": user_prompt},
        ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        logger.info("LLM JSON request: model=%s tokens=%d", self.model, max_tokens)

        # Retry with exponential backoff for transient server errors
        import asyncio as _asyncio
        last_error = None
        for attempt in range(4):  # up to 4 attempts
            resp = await self._client.post("/chat/completions", json=payload)
            if resp.status_code in (500, 502, 503, 429):
                wait = (2 ** attempt) + 1  # 2s, 3s, 5s, 9s
                logger.warning("LLM API error %d, retrying in %ds (attempt %d/4)", resp.status_code, wait, attempt + 1)
                last_error = resp
                await _asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            break
        else:
            # All retries exhausted
            last_error.raise_for_status()

        data = resp.json()

        raw = data["choices"][0]["message"]["content"]

        # Strip markdown fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (e.g. ```json)
            cleaned = re.sub(r"^```\w*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            # Best-effort repair: if the LLM was truncated mid-string by
            # max_tokens, close the open string and any open braces/brackets.
            repaired = _repair_truncated_json(cleaned)
            if repaired is not None:
                try:
                    parsed = json.loads(repaired)
                    logger.warning(
                        "LLM JSON was truncated (%s); recovered via repair (lost some content)",
                        e,
                    )
                    return parsed
                except json.JSONDecodeError:
                    pass

            logger.error("Failed to parse LLM JSON response: %s", e)
            logger.debug("Raw response (last 500): %s", cleaned[-500:])
            raise ValueError(f"LLM returned invalid JSON: {e}") from e

    async def close(self) -> None:
        await self._client.aclose()
