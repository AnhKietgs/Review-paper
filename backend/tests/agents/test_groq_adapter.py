"""Bounded provider retry, schema repair and sanitized failure."""

from types import SimpleNamespace

import httpx
import pytest
from groq import APIStatusError, RateLimitError

from app.agents.ports import LLMFailure, RateLimitPause
from app.agents.schemas import AgentAction
from app.infrastructure.groq.client import GroqClient


def test_rate_limit_wait_is_bounded_to_five_minutes_and_safe():
    calls = []
    waits = []

    def completion(**_kwargs):
        calls.append(1)
        raise RateLimitError(
            "secret-token",
            response=httpx.Response(
                429,
                headers={"retry-after": "75"},
                request=httpx.Request("POST", "https://example.invalid"),
            ),
            body=None,
        )

    adapter = GroqClient(
        "secret-token",
        "configured-model",
        completion=completion,
        sleep=waits.append,
    )
    with pytest.raises(LLMFailure, match="rate_limited") as error:
        adapter.generate_json([{"role": "user", "content": "JSON please"}], AgentAction)
    assert len(calls) == 5
    assert waits == [75, 75, 75, 75]
    assert "secret-token" not in str(error.value)


def test_short_retry_after_can_recover_after_more_than_two_retries():
    calls = []
    waits = []

    def completion(**_kwargs):
        calls.append(1)
        if len(calls) <= 3:
            raise RateLimitError(
                "rate limit",
                response=httpx.Response(
                    429,
                    headers={"retry-after": "10"},
                    request=httpx.Request("POST", "https://example.invalid"),
                ),
                body=None,
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"action":"finish","reason":"Done","reference_paper_id":null}'
            ))],
            usage=SimpleNamespace(total_tokens=10),
        )

    adapter = GroqClient("key", "model", completion=completion, sleep=waits.append)
    assert adapter.generate_json([], AgentAction).action == "finish"
    assert len(calls) == 4
    assert waits == [10, 10, 10]


def test_retry_after_beyond_budget_fails_without_waiting():
    waits = []
    calls = []

    def completion(**_kwargs):
        calls.append(1)
        raise RateLimitError(
            "rate limit",
            response=httpx.Response(
                429,
                headers={"retry-after": "3600"},
                request=httpx.Request("POST", "https://example.invalid"),
            ),
            body=None,
        )

    adapter = GroqClient("key", "model", completion=completion, sleep=waits.append)
    with pytest.raises(RateLimitPause, match="rate_limited") as error:
        adapter.generate_json([], AgentAction)
    assert len(calls) == 1
    assert waits == []
    assert error.value.retry_after_seconds == 300


def test_schema_repair_shares_the_same_five_minute_wait_budget():
    calls = []
    waits = []

    def completion(**_kwargs):
        calls.append(1)
        if len(calls) in {1, 3}:
            raise RateLimitError(
                "rate limit",
                response=httpx.Response(
                    429,
                    headers={"retry-after": "200"},
                    request=httpx.Request("POST", "https://example.invalid"),
                ),
                body=None,
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=SimpleNamespace(total_tokens=10),
        )

    adapter = GroqClient("key", "model", completion=completion, sleep=waits.append)
    with pytest.raises(LLMFailure, match="rate_limited"):
        adapter.generate_json([], AgentAction)
    assert len(calls) == 3
    assert waits == [200]


def test_schema_gets_only_one_repair():
    responses = iter(
        ["{}", '{"action":"finish","reason":"Done","reference_paper_id":null}']
    )
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=next(responses)))],
            usage=SimpleNamespace(total_tokens=10),
        )

    adapter = GroqClient("key", "model", completion=completion)
    assert (
        adapter.generate_json([{"role": "user", "content": "JSON"}], AgentAction).action
        == "finish"
    )
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert adapter.usage["tokens"] == 20


def test_oversized_request_is_not_retried_as_provider_outage():
    calls = []

    def completion(**_kwargs):
        calls.append(1)
        raise APIStatusError(
            "secret-token",
            response=httpx.Response(
                413, request=httpx.Request("POST", "https://example.invalid")
            ),
            body=None,
        )

    adapter = GroqClient("secret-token", "model", completion=completion)
    with pytest.raises(LLMFailure, match="request_too_large") as error:
        adapter.generate_json([], AgentAction)
    assert len(calls) == 1
    assert "secret-token" not in str(error.value)


def test_completion_budget_is_passed_to_provider():
    requests = []

    def completion(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"action":"finish","reason":"Done","reference_paper_id":null}'
            ))],
            usage=SimpleNamespace(total_tokens=10),
        )

    adapter = GroqClient(
        "key", "model", completion=completion, max_completion_tokens=3072
    )
    assert adapter.generate_json([], AgentAction).action == "finish"
    assert requests[0]["max_completion_tokens"] == 3072


def test_provider_json_validation_failure_gets_one_retry():
    requests = []

    def completion(**kwargs):
        requests.append(kwargs)
        if len(requests) == 1:
            raise APIStatusError(
                "Generated JSON could not be validated",
                response=httpx.Response(
                    400, request=httpx.Request("POST", "https://example.invalid")
                ),
                body={"error": {"code": "json_validate_failed"}},
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"action":"finish","reason":"Done","reference_paper_id":null}'
            ))],
            usage=SimpleNamespace(total_tokens=10),
        )

    adapter = GroqClient("key", "model", completion=completion)
    assert adapter.generate_json([], AgentAction).action == "finish"
    assert len(requests) == 2


def test_repeated_provider_json_validation_failure_is_not_outage():
    requests = []

    def completion(**kwargs):
        requests.append(kwargs)
        raise APIStatusError(
            "secret-token",
            response=httpx.Response(
                400, request=httpx.Request("POST", "https://example.invalid")
            ),
            body={"error": {"code": "json_validate_failed"}},
        )

    adapter = GroqClient("secret-token", "model", completion=completion)
    with pytest.raises(LLMFailure, match="invalid_model_output") as error:
        adapter.generate_json([], AgentAction)
    assert len(requests) == 2
    assert "secret-token" not in str(error.value)
