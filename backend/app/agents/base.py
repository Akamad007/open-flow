"""Base agent class — shared infrastructure for all agents."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from app.providers.llm.base import LLMProvider


@dataclass
class AgentResult:
    """Standard result from an agent run."""
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class BaseAgent(ABC):
    """
    Abstract base for all pipeline agents.

    Each agent:
    - Receives an LLMProvider for reasoning
    - Has a run() method that produces an AgentResult
    - Logs all decisions for observability
    - Handles errors gracefully
    """

    def __init__(self, llm: LLMProvider, logger_name: Optional[str] = None):
        self.llm = llm
        self.logger = logging.getLogger(logger_name or self.__class__.__name__)

    @abstractmethod
    async def run(self, context: dict[str, Any]) -> AgentResult:
        """
        Execute the agent's task.

        Args:
            context: Dictionary containing all inputs the agent needs.
                     Keys vary per agent.

        Returns:
            AgentResult with success flag, data payload, and any errors/warnings.
        """
        ...

    def _load_prompt_template(self, filename: str) -> str:
        """Load a prompt template from the prompts directory."""
        from pathlib import Path
        template_path = Path(__file__).parent.parent / "prompts" / filename
        if not template_path.exists():
            self.logger.warning("Prompt template not found: %s", filename)
            return ""
        return template_path.read_text()
