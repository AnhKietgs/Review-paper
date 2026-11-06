"""Groq JSON adapter with explicit retry and schema validation budgets."""

import json
import math
import time

from groq import APIError, Groq, RateLimitError
from pydantic import ValidationError

from app.agents.ports import LLMFailure, RateLimitPause, RunCancelled
from app.infrastructure.groq.quota import GroqQuota, estimate_input_tokens
from app.infrastructure.groq.failures import provider_failure, provider_retry_delay

MAX_RATE_LIMIT_WAIT_SECONDS = 300


class GroqClient:
    """Call configured Groq model without exposing credentials in failures."""

    evidence_selection_mode = True

    def __init__(  # pylint: disable=too-many-arguments
        self,
        api_key: str,
        model: str,
        completion=None,
        sleep=time.sleep,
        on_retry=None,
        rate_limit_wait_seconds: int = 60,
        max_completion_tokens: int = 4096,
        *,
        quota: GroqQuota | None = None,
        on_quota=None,
        is_cancelled=None,
        on_provider_event=None,
        budget=None,
    ):
        self.model = model
        self._completion = (
            completion
            or Groq(
                api_key=api_key,
                max_retries=0,
                timeout=30,
            ).chat.completions.create
        )
        self._sleep = sleep
        self._on_retry = on_retry
        self._rate_limit_wait_seconds = max(1, rate_limit_wait_seconds)
        self._max_completion_tokens = max(1, max_completion_tokens)
        self._quota = quota
        self._events = {
            "quota": on_quota, "provider": on_provider_event, "budget": budget,
        }
        self._is_cancelled = is_cancelled
        self.usage = {"calls": 0, "tokens": 0}

    def _retry_wait(self, error: RateLimitError) -> int:
        """Honor Groq's retry-after seconds, falling back to local policy."""
        header = error.response.headers.get("retry-after")
        try:
            seconds = float(header) if header is not None else 0
        except ValueError:
            seconds = 0
        if not math.isfinite(seconds) or seconds <= 0:
            return self._rate_limit_wait_seconds
        return max(1, math.ceil(seconds))

    @staticmethod
    def _rate_limit_details(error: RateLimitError) -> dict[str, str]:
        """Expose only provider quota headers useful for diagnosing a 429."""
        allowed = (
            "retry-after",
            "x-ratelimit-limit-requests",
            "x-ratelimit-limit-tokens",
            "x-ratelimit-remaining-requests",
            "x-ratelimit-remaining-tokens",
            "x-ratelimit-reset-requests",
            "x-ratelimit-reset-tokens",
        )
        details = {
            name: error.response.headers[name]
            for name in allowed
            if name in error.response.headers
        }
        body = getattr(error, "body", None)
        provider_error = body.get("error", body) if isinstance(body, dict) else None
        if isinstance(provider_error, dict):
            for name in ("code", "type"):
                value = provider_error.get(name)
                if isinstance(value, str):
                    details[f"error_{name}"] = value[:80]
        return details

    def _completion_budget(self, input_tokens: int) -> int:
        """Fit a useful completion into a whole quota window without cutting sources."""
        if self._quota is None:
            return self._max_completion_tokens
        available = self._quota.tokens_per_minute - input_tokens - 128
        if available < min(1024, self._max_completion_tokens):
            raise LLMFailure("quota_request_too_large")
        return min(self._max_completion_tokens, available)

    def _quota_event(self, input_tokens, output_tokens, wait_seconds=0) -> None:
        if self._events["quota"]:
            self._events["quota"]({
                "model": self.model,
                "estimated_input_tokens": input_tokens,
                "reserved_output_tokens": output_tokens,
                "wait_seconds": wait_seconds,
            })

    def _wait(self, pause: RateLimitPause, rate_waited: list, attempt: int) -> None:
        """Bound inline waiting without shortening the provider's next deadline."""
        seconds = pause.retry_after_seconds
        if rate_waited[0] + seconds > MAX_RATE_LIMIT_WAIT_SECONDS:
            raise pause
        rate_waited[0] += seconds
        if self._on_retry:
            self._on_retry(attempt, seconds)
        self._sleep_interruptibly(seconds)

    def _sleep_interruptibly(self, seconds: int) -> None:
        """Both quota and provider recovery waits remain cancellable."""
        if self._is_cancelled is None:
            self._sleep(seconds)
        else:
            for _ in range(seconds):
                self._check_cancelled()
                self._sleep(1)
            self._check_cancelled()

    def _check_cancelled(self) -> None:
        """Cooperate with user cancellation between calls and quota wait slices."""
        if self._is_cancelled is not None and self._is_cancelled():
            raise RunCancelled("cancelled_by_user")

    def _request(self, messages, rate_waited, provider_retries):
        rate_retries = 0
        json_retries = 0
        input_tokens = estimate_input_tokens(messages)
        output_tokens = self._completion_budget(input_tokens)
        budget = self._events["budget"]
        while True:
            self._check_cancelled()
            if budget:
                budget.check(input_tokens + output_tokens)
            reservation = None
            if self._quota:
                try:
                    reservation = self._quota.reserve(
                        self.model, input_tokens + output_tokens
                    )
                except RateLimitPause as pause:
                    self._quota_event(
                        input_tokens, output_tokens, pause.retry_after_seconds
                    )
                    rate_retries += 1
                    self._wait(pause, rate_waited, rate_retries)
                    continue
                self._quota_event(input_tokens, output_tokens)
            try:
                self._check_cancelled()
                charged = budget.reserve(input_tokens + output_tokens) if budget else 0
                self.usage["calls"] += 1
                response = self._completion(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0,
                    max_completion_tokens=output_tokens,
                )
                tokens = getattr(response.usage, "total_tokens", 0) or 0
                self.usage["tokens"] += tokens
                if budget and tokens > 0:
                    budget.reconcile(charged, tokens)
                if reservation is not None and tokens > 0:
                    self._quota.reconcile(reservation, tokens)
                return response.choices[0].message.content
            except RateLimitError as exc:
                if budget:
                    budget.reconcile(charged, 0)
                wait_seconds = self._retry_wait(exc)
                if reservation is not None:
                    self._quota.reconcile(reservation, 0)
                    self._quota.defer(self.model, wait_seconds)
                rate_retries += 1
                self._wait(
                    RateLimitPause(wait_seconds, self._rate_limit_details(exc)),
                    rate_waited, rate_retries,
                )
            except APIError as exc:
                body = getattr(exc, "body", None)
                error = body.get("error", body) if isinstance(body, dict) else None
                code = error.get("code") if isinstance(error, dict) else None
                if (
                    getattr(exc, "status_code", None) == 400
                    and code == "json_validate_failed"
                ):
                    if json_retries:
                        raise LLMFailure("invalid_model_output") from exc
                    json_retries += 1
                    continue
                self._handle_provider_error(exc, provider_retries)

    def _handle_provider_error(self, error, retries):
        """Retry temporary failures at most twice across one structured generation."""
        failure = provider_failure(error)
        retries[0] += 1
        delay = provider_retry_delay(error, retries[0])
        retrying = failure.retryable and retries[0] <= 2 and delay <= 30
        if self._events["provider"]:
            self._events["provider"]({
                **failure.details, "model": self.model, "error_code": str(failure),
                "retryable": failure.retryable, "retrying": retrying,
                "retry_number": retries[0], "max_retries": 2,
                "wait_seconds": delay if retrying else 0,
            })
        if not retrying:
            raise failure from error
        self._sleep_interruptibly(delay)

    def generate_json(self, messages, schema):
        """Parse structured output and allow one schema-only repair attempt."""
        rate_waited = [0]
        provider_retries = [0]
        request = self.schema_request(messages, schema)
        for attempt in range(2):
            content = self._request(request, rate_waited, provider_retries)
            try:
                return schema.model_validate_json(content or "")
            except ValidationError as exc:
                if attempt:
                    raise LLMFailure("invalid_model_output") from exc
                request.append(
                    {
                        "role": "user",
                        "content": "Previous output failed the JSON schema. "
                        "Return a valid object, preserving source IDs and exact quotes "
                        "from the original context.",
                    }
                )
        raise LLMFailure("invalid_model_output")

    @staticmethod
    def schema_request(messages, schema):
        """The planner and sender must count the same schema and chat framing."""
        return list(messages) + [
            {
                "role": "system",
                "content": "Return only JSON matching this schema: "
                + json.dumps(schema.model_json_schema(), ensure_ascii=False),
            }
        ]

    def fits_request(self, messages, schema) -> bool:
        """Leave full output budget plus room for framing/schema-repair overhead."""
        if self._quota is None:
            return True
        tokens = estimate_input_tokens(self.schema_request(messages, schema))
        return (
            tokens + self._max_completion_tokens + 256
            <= self._quota.tokens_per_minute
        )
