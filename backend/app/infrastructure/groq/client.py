"""Groq JSON adapter with explicit retry and schema validation budgets."""

import json
import math
import time

from groq import APIError, Groq, RateLimitError
from pydantic import ValidationError

from app.agents.ports import LLMFailure

MAX_RATE_LIMIT_WAIT_SECONDS = 300


class GroqClient:
    """Call configured Groq model without exposing credentials in failures."""

    def __init__(
        self,
        api_key: str,
        model: str,
        completion=None,
        sleep=time.sleep,
        on_retry=None,
        rate_limit_wait_seconds: int = 60,
        max_completion_tokens: int = 4096,
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

    def _request(self, messages, rate_waited):
        rate_retries = 0
        json_retries = 0
        while True:
            try:
                self.usage["calls"] += 1
                response = self._completion(
                    model=self.model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0,
                    max_completion_tokens=self._max_completion_tokens,
                )
                self.usage["tokens"] += getattr(response.usage, "total_tokens", 0) or 0
                return response.choices[0].message.content
            except RateLimitError as exc:
                wait_seconds = self._retry_wait(exc)
                if rate_waited[0] + wait_seconds > MAX_RATE_LIMIT_WAIT_SECONDS:
                    raise LLMFailure("rate_limited") from exc
                rate_retries += 1
                rate_waited[0] += wait_seconds
                if self._on_retry:
                    self._on_retry(rate_retries, wait_seconds)
                self._sleep(wait_seconds)
            except APIError as exc:
                if getattr(exc, "status_code", None) == 413:
                    raise LLMFailure("request_too_large") from exc
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
                raise LLMFailure("provider_unavailable") from exc

    def generate_json(self, messages, schema):
        """Parse structured output and allow one schema-only repair attempt."""
        rate_waited = [0]
        request = list(messages) + [
            {
                "role": "system",
                "content": "Return only JSON matching this schema: "
                + json.dumps(schema.model_json_schema(), ensure_ascii=False),
            }
        ]
        for attempt in range(2):
            content = self._request(request, rate_waited)
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
