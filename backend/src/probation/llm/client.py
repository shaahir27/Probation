"""LLM client interface for Nebius Token Factory with schema validation and budget guard.

Authority: docs/CONTRACT.md section 6 and invariants I-1, I-3, I-15, I-16.
"""

from typing import TypeVar

from pydantic import BaseModel

from probation.config import settings
from probation.llm.budget import BudgetGuard

T = TypeVar("T", bound=BaseModel)


class LLMValidationError(Exception):
    """Raised when LLM output fails schema validation or repair."""

    pass


class LLMClient:
    """Client for Nebius Token Factory inference with budget guard and retries."""

    def __init__(
        self,
        base_url: str = settings.llm_base_url,
        api_key: str = settings.llm_api_key,
        budget_guard: BudgetGuard | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.budget_guard = budget_guard or BudgetGuard()

    def generate_structured(
        self,
        prompt: str,
        response_model: type[T],
        model: str = settings.model_reader,
        system_prompt: str | None = None,
    ) -> T:
        """Execute a prompt against the model and validate against the Pydantic schema."""
        # Detailed implementation is completed in Phase 1
        raise NotImplementedError("LLMClient.generate_structured is implemented in Phase 1.")
