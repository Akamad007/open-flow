"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from typing import Any, Optional, Type

from pydantic import BaseModel


class LLMProvider(ABC):
    """Abstract base class for LLM providers used by agents."""

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: Optional[Type[BaseModel]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Send a completion request to the LLM.

        Args:
            system_prompt: System-level instructions.
            user_prompt: User message / task description.
            response_format: Optional Pydantic model for structured output.
            temperature: Sampling temperature.
            max_tokens: Maximum response tokens.

        Returns:
            The LLM's response text (or JSON string if response_format is given).
        """
        ...

    @abstractmethod
    async def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """
        Send a completion request and parse the response as JSON.

        Returns:
            Parsed JSON dict from the LLM response.
        """
        ...
