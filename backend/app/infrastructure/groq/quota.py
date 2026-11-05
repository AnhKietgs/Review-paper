"""Thread-safe rolling quota reservations shared by local Groq agents."""

import math
import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock

from app.agents.ports import LLMFailure, RateLimitPause


def estimate_input_tokens(messages: list[dict]) -> int:
    """Approximate UTF-8 input including schema text and chat framing.

    This deliberately reserves more than a characters/4 estimate for Vietnamese.
    It is a heuristic, not the provider tokenizer; usage corrects it afterward.
    """
    size = sum(
        len(str(value).encode("utf-8"))
        for message in messages for value in message.values()
    )
    return math.ceil(size / 3) + 12 * len(messages) + 32


@dataclass
class Reservation:
    """One request's provisional token charge until its window expires."""

    timestamp: float
    tokens: int


@dataclass
class ModelWindow:
    """Shared usage and provider deadline for one model."""

    reservations: deque = field(default_factory=deque)
    blocked_until: float = 0


class GroqQuota:
    """One coordinator for all clients in the single local worker process."""

    def __init__(
        self, tokens_per_minute=8000, requests_per_minute=30,
        clock=time.monotonic,
    ):
        self.tokens_per_minute = max(1, tokens_per_minute)
        self.requests_per_minute = max(1, requests_per_minute)
        self._clock = clock
        self._models: dict[str, ModelWindow] = {}
        self._lock = Lock()

    def reserve(self, model: str, estimated_tokens: int) -> Reservation:
        """Reserve atomically or pause until enough local/provider quota exists."""
        if estimated_tokens > self.tokens_per_minute:
            raise LLMFailure("quota_request_too_large")
        with self._lock:
            now = self._clock()
            window = self._models.setdefault(model, ModelWindow())
            while (
                window.reservations
                and window.reservations[0].timestamp + 60 <= now
            ):
                window.reservations.popleft()
            available = self.tokens_per_minute - sum(
                item.tokens for item in window.reservations
            )
            requests = len(window.reservations)
            ready_at = max(now, window.blocked_until)
            for item in window.reservations:
                if (
                    available >= estimated_tokens
                    and requests < self.requests_per_minute
                ):
                    break
                available += item.tokens
                requests -= 1
                ready_at = max(ready_at, item.timestamp + 60)
            if ready_at > now:
                raise RateLimitPause(
                    math.ceil(ready_at - now),
                    provider_details={
                        "reason": "quota_wait", "model": model,
                        "estimated_tokens": estimated_tokens,
                        "tokens_per_minute": self.tokens_per_minute,
                    },
                )
            reservation = Reservation(now, max(1, estimated_tokens))
            window.reservations.append(reservation)
            return reservation

    def reconcile(self, reservation: Reservation, actual_tokens: int) -> None:
        """Replace token charge; rejected calls still count as requests."""
        with self._lock:
            reservation.tokens = max(0, actual_tokens)

    def defer(self, model: str, seconds: int) -> None:
        """Honor a provider deadline for every client using this model."""
        with self._lock:
            window = self._models.setdefault(model, ModelWindow())
            window.blocked_until = max(
                window.blocked_until, self._clock() + max(0, seconds)
            )
