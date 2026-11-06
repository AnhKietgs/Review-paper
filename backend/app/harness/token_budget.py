"""Conservative token admission shared by all model roles within one review."""

from dataclasses import dataclass

from app.agents.ports import LLMFailure


@dataclass
class RunTokenBudget:
    """Reserve complete requests; unknown provider usage stays charged."""

    limit: int
    spent: int = 0

    def check(self, tokens: int) -> None:
        """Never wait or send a request that cannot fit the review allowance."""
        if self.spent + tokens > self.limit:
            raise LLMFailure("review_token_budget_exhausted")

    def reserve(self, tokens: int) -> int:
        """Charge immediately before an actual HTTP attempt."""
        self.check(tokens)
        self.spent += tokens
        return tokens

    def reconcile(self, reserved: int, actual: int) -> None:
        """Use reported total usage, or release a confirmed rejected request."""
        self.spent += max(0, actual) - reserved
