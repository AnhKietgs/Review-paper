"""Provider-neutral structured generation interface."""

from typing import Protocol, TypeVar

from pydantic import BaseModel

OutputModel = TypeVar("OutputModel", bound=BaseModel)
Message = dict[str, str]


class LLMPort(Protocol):
    """The sole model interface available to graph nodes."""

    def generate_json(
        self, messages: list[Message], schema: type[OutputModel]
    ) -> OutputModel:
        """Generate and validate one structured model response."""
        ...


class LLMFailure(RuntimeError):
    """Sanitized provider failure safe to expose to a run trace."""


class RateLimitPause(LLMFailure):
    """Retryable provider limit with a sanitized delay in seconds."""

    def __init__(self, retry_after_seconds: int, provider_details=None):
        super().__init__("rate_limited")
        self.retry_after_seconds = retry_after_seconds
        self.provider_details = provider_details or {}
