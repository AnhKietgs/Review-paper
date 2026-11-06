"""Shared run admission budget bounds actual HTTP calls, including retries."""

from types import SimpleNamespace

import httpx
import pytest
from groq import APITimeoutError, RateLimitError

from app.agents.ports import LLMFailure
from app.agents.schemas import AgentAction
from app.harness.token_budget import RunTokenBudget
from app.infrastructure.groq.client import GroqClient


def answer(tokens=20, content='{"action":"finish","reason":"Done"}'):
    return SimpleNamespace(
        usage=SimpleNamespace(total_tokens=tokens),
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
    )


def test_shared_budget_reconciles_and_blocks_all_roles_before_http():
    budget, calls = RunTokenBudget(10000, 0), []

    def completion(**_kwargs):
        calls.append(1)
        return answer(100)

    first = GroqClient("fake", "20b", completion=completion, budget=budget)
    first.generate_json([], AgentAction)
    assert budget.spent == 100
    budget.limit = 101
    second = GroqClient("fake", "120b", completion=completion, budget=budget)
    with pytest.raises(LLMFailure, match="review_token_budget_exhausted"):
        second.generate_json([], AgentAction)
    assert calls == [1]
    assert budget.spent == 100


def test_schema_repair_requires_another_budget_admission():
    budget, calls = RunTokenBudget(10000, 0), []

    def completion(**_kwargs):
        calls.append(1)
        budget.limit = 101
        return answer(100, "{}")

    client = GroqClient("fake", "20b", completion=completion, budget=budget)
    with pytest.raises(LLMFailure, match="review_token_budget_exhausted"):
        client.generate_json([], AgentAction)
    assert calls == [1]
    assert budget.spent == 100


def test_uncertain_timeout_cost_is_retained_and_retry_must_fit_budget():
    budget, calls = RunTokenBudget(5000, 0), []

    def completion(**_kwargs):
        calls.append(1)
        raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))

    client = GroqClient(
        "fake", "20b", completion=completion, budget=budget, sleep=lambda _: None,
    )
    with pytest.raises(LLMFailure, match="review_token_budget_exhausted"):
        client.generate_json([], AgentAction)
    assert calls == [1]
    assert budget.spent > 4096


def test_rejected_rate_limit_releases_budget_before_retry():
    budget, calls = RunTokenBudget(5000, 0), []

    def completion(**_kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RateLimitError("limited", body=None, response=httpx.Response(
                429, headers={"retry-after": "1"},
                request=httpx.Request("POST", "https://example.invalid"),
            ))
        return answer(100)

    client = GroqClient(
        "fake", "20b", completion=completion, budget=budget, sleep=lambda _: None,
    )
    client.generate_json([], AgentAction)
    assert len(calls) == 2
    assert budget.spent == 100
