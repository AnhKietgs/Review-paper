"""Bounded provider retry, schema repair and sanitized failure."""

from types import SimpleNamespace

import httpx
import pytest
from groq import APIStatusError, RateLimitError

from app.agents.ports import LLMFailure, RateLimitPause
from app.agents.schemas import AgentAction
from app.infrastructure.groq.client import GroqClient
from app.infrastructure.groq.quota import GroqQuota


def test_cancel_during_quota_wait_prevents_another_provider_call():
    from app.agents.ports import RunCancelled

    calls, waits = [], []

    def completion(**_kwargs):
        calls.append(1)
        raise RateLimitError(
            "limited", response=httpx.Response(
                429, headers={"retry-after": "60"},
                request=httpx.Request("POST", "https://example.invalid"),
            ), body=None,
        )

    adapter = GroqClient(
        "fake", "model", completion=completion, sleep=waits.append,
        is_cancelled=lambda: len(waits) >= 2,
    )
    with pytest.raises(RunCancelled):
        adapter.generate_json([], AgentAction)
    assert calls == [1]
    assert waits == [1, 1]


def test_cancelled_run_never_sends_a_provider_request():
    from app.agents.ports import RunCancelled

    calls = []
    adapter = GroqClient(
        "fake", "model", completion=lambda **_kwargs: calls.append(1),
        is_cancelled=lambda: True,
    )
    with pytest.raises(RunCancelled):
        adapter.generate_json([], AgentAction)
    assert calls == []


def test_rate_limit_wait_is_bounded_to_five_minutes_and_safe():
    calls = []
    waits = []

    def completion(**_kwargs):
        calls.append(1)
        raise RateLimitError(
            "secret-token",
            response=httpx.Response(
                429,
                headers={
                    "retry-after": "15",
                    "x-ratelimit-limit-tokens": "8000",
                    "x-ratelimit-remaining-tokens": "0",
                    "x-ratelimit-reset-tokens": "48s",
                },
                request=httpx.Request("POST", "https://example.invalid"),
            ),
            body={"error": {"code": "rate_limit_exceeded", "type": "tokens"}},
        )

    adapter = GroqClient(
        "secret-token",
        "configured-model",
        completion=completion,
        sleep=waits.append,
    )
    with pytest.raises(LLMFailure, match="rate_limited") as error:
        adapter.generate_json([{"role": "user", "content": "JSON please"}], AgentAction)
    assert len(calls) == 21
    assert waits == [15] * 20
    assert "secret-token" not in str(error.value)
    assert error.value.provider_details == {
        "retry-after": "15",
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "0",
        "x-ratelimit-reset-tokens": "48s",
        "error_code": "rate_limit_exceeded",
        "error_type": "tokens",
    }


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


def test_retry_after_beyond_inline_budget_keeps_full_provider_deadline():
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
    assert error.value.retry_after_seconds == 3600


def test_agents_share_quota_before_network_calls_across_client_instances():
    now = [0.0]
    call_times = []
    estimates = []

    def completion(**_kwargs):
        call_times.append(now[0])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"action":"finish","reason":"Done","reference_paper_id":null}'
            ))],
            usage=SimpleNamespace(total_tokens=1500),
        )

    def sleep(seconds):
        now[0] += seconds

    quota = GroqQuota(tokens_per_minute=2000, clock=lambda: now[0])
    for _role in ("supervisor", "related_work"):
        adapter = GroqClient(
            "key", "20b", completion=completion, sleep=sleep,
            max_completion_tokens=1000, quota=quota, on_quota=estimates.append,
        )
        adapter.generate_json([], AgentAction)
    assert call_times == [0, 60]
    assert estimates[0]["estimated_input_tokens"] > 0  # Includes JSON schema.
    assert estimates[0]["reserved_output_tokens"] == 1000
    assert any(item["wait_seconds"] == 60 for item in estimates)


def test_long_provider_deadline_blocks_other_agent_without_network_call():
    calls = []
    quota = GroqQuota(clock=lambda: 0)

    def completion(**_kwargs):
        calls.append(1)
        raise RateLimitError(
            "limited", body=None,
            response=httpx.Response(
                429, headers={"retry-after": "381"},
                request=httpx.Request("POST", "https://example.invalid"),
            ),
        )

    for _agent in range(2):
        adapter = GroqClient(
            "key", "20b", completion=completion, quota=quota,
            sleep=lambda _seconds: pytest.fail("Long pause must be durable"),
        )
        with pytest.raises(RateLimitPause) as error:
            adapter.generate_json([], AgentAction)
        assert error.value.retry_after_seconds == 381
    assert len(calls) == 1


def test_short_provider_retry_recovers_with_shared_clock_and_reservation():
    now = [0.0]
    call_times = []

    def completion(**_kwargs):
        call_times.append(now[0])
        if len(call_times) == 1:
            raise RateLimitError(
                "limited", body=None,
                response=httpx.Response(
                    429, headers={"retry-after": "10"},
                    request=httpx.Request("POST", "https://example.invalid"),
                ),
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"action":"finish","reason":"Done","reference_paper_id":null}'
            ))],
            usage=SimpleNamespace(total_tokens=100),
        )

    def sleep(seconds):
        now[0] += seconds

    quota = GroqQuota(clock=lambda: now[0])
    adapter = GroqClient(
        "key", "20b", completion=completion, quota=quota, sleep=sleep,
    )
    assert adapter.generate_json([], AgentAction).action == "finish"
    assert call_times == [0, 10]
    assert adapter.usage == {"calls": 2, "tokens": 100}


def test_output_budget_fits_available_window_without_truncating_input():
    requests = []
    events = []

    def completion(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"action":"finish","reason":"Done","reference_paper_id":null}'
            ))],
            usage=SimpleNamespace(total_tokens=1000),
        )

    adapter = GroqClient(
        "key", "20b", completion=completion, max_completion_tokens=4096,
        quota=GroqQuota(tokens_per_minute=2000), on_quota=events.append,
    )
    adapter.generate_json(
        [{"role": "user", "content": "Keep this source."}], AgentAction
    )
    assert 1024 <= requests[0]["max_completion_tokens"] < 2000
    assert requests[0]["messages"][0]["content"] == "Keep this source."
    assert events[0]["reserved_output_tokens"] == requests[0]["max_completion_tokens"]


def test_request_that_cannot_fit_minimum_json_budget_never_calls_provider():
    calls = []
    adapter = GroqClient(
        "key", "20b", completion=lambda **kwargs: calls.append(kwargs),
        quota=GroqQuota(tokens_per_minute=100),
    )
    with pytest.raises(LLMFailure, match="quota_request_too_large"):
        adapter.generate_json([], AgentAction)
    assert not calls


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
                    headers={"retry-after": "40"},
                    request=httpx.Request("POST", "https://example.invalid"),
                ),
                body=None,
            )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            usage=SimpleNamespace(total_tokens=10),
        )

    adapter = GroqClient("key", "model", completion=completion, sleep=waits.append)
    with pytest.raises(LLMFailure, match="invalid_model_output"):
        adapter.generate_json([], AgentAction)
    assert len(calls) == 4
    assert waits == [40, 40]


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
