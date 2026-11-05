"""Shared proactive quotas use a controllable clock and no live Groq calls."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.agents.ports import LLMFailure, RateLimitPause
from app.infrastructure.groq.quota import GroqQuota, estimate_input_tokens


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_input_estimate_includes_vietnamese_and_message_overhead():
    assert estimate_input_tokens([]) > 0
    assert estimate_input_tokens([{"role": "user", "content": "đạo đức"}]) > (
        estimate_input_tokens([{"role": "user", "content": "a"}])
    )


def test_shared_model_reserves_input_and_output_until_window_expires():
    clock = Clock()
    quota = GroqQuota(tokens_per_minute=100, clock=clock)
    quota.reserve("20b", 80)
    with pytest.raises(RateLimitPause) as error:
        quota.reserve("20b", 30)
    assert error.value.retry_after_seconds == 60
    quota.reserve("120b", 80)
    clock.sleep(60)
    quota.reserve("20b", 100)


def test_actual_usage_releases_unused_completion_reservation():
    quota = GroqQuota(tokens_per_minute=100)
    reservation = quota.reserve("20b", 90)
    quota.reconcile(reservation, 10)
    quota.reserve("20b", 90)


def test_overestimated_usage_does_not_create_quota_credit():
    quota = GroqQuota(tokens_per_minute=100)
    reservation = quota.reserve("20b", 50)
    quota.reconcile(reservation, 120)
    with pytest.raises(RateLimitPause):
        quota.reserve("20b", 1)


def test_request_limit_remains_after_rejected_token_reservation():
    quota = GroqQuota(requests_per_minute=1)
    reservation = quota.reserve("20b", 80)
    quota.reconcile(reservation, 0)
    with pytest.raises(RateLimitPause):
        quota.reserve("20b", 1)


def test_provider_cooldown_is_shared_and_never_shortened_to_five_minutes():
    clock = Clock()
    quota = GroqQuota(clock=clock)
    quota.defer("20b", 381)
    clock.sleep(60)
    with pytest.raises(RateLimitPause) as error:
        quota.reserve("20b", 1)
    assert error.value.retry_after_seconds == 321
    quota.defer("20b", 1)
    clock.sleep(321)
    quota.reserve("20b", 1)


def test_oversized_request_is_rejected_instead_of_waiting_forever():
    quota = GroqQuota(tokens_per_minute=100)
    with pytest.raises(LLMFailure, match="quota_request_too_large"):
        quota.reserve("20b", 101)


def test_concurrent_agents_cannot_overreserve_a_model():
    quota = GroqQuota(tokens_per_minute=100)

    def attempt(_index):
        try:
            quota.reserve("20b", 60)
            return True
        except RateLimitPause:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count(True) == 1
