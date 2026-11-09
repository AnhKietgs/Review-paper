"""Quota coordination must outlive clients reconstructed on every worker turn."""

from app.core.config import Settings
from app.harness.events import RunEventRecorder
from app.workers.run_worker import RunWorker


def test_one_worker_shares_its_coordinator_across_agents_and_turns(monkeypatch):
    clients = []

    class Client:
        def __init__(self, *_args, **kwargs):
            clients.append(kwargs)

    monkeypatch.setattr("app.workers.run_worker.GroqClient", Client)
    worker = RunWorker()
    events = RunEventRecorder()
    settings = Settings.from_env()
    worker._create_groq_router(settings, "run", events)
    worker._create_groq_router(settings, "run", events)
    assert len(clients) == 12
    assert all(item["quota"] is worker.quota for item in clients)
    clients[0]["on_quota"]({
        "model": "20b", "estimated_input_tokens": 700,
        "reserved_output_tokens": 256, "wait_seconds": 60,
    })
    assert events.items[-1]["action"] == "quota_wait"
    assert events.items[-1]["payload"]["estimated_input_tokens"] == 700


def test_quota_limits_are_environment_configurable(monkeypatch):
    monkeypatch.setenv("GROQ_TOKENS_PER_MINUTE", "6000")
    monkeypatch.setenv("GROQ_REQUESTS_PER_MINUTE", "20")
    worker = RunWorker()
    assert worker.quota.tokens_per_minute == 6000
    assert worker.quota.requests_per_minute == 20


def test_scientific_phase_adapters_share_budget_and_keep_one_logical_agent(monkeypatch):
    from app.harness.token_budget import RunTokenBudget

    class Client:
        def __init__(self, _key, model, **kwargs):
            self.model, self.options = model, kwargs

    monkeypatch.setattr("app.workers.run_worker.GroqClient", Client)
    worker, events = RunWorker(), RunEventRecorder()
    budget = RunTokenBudget(50000)
    router = worker._create_groq_router(Settings.from_env(), "run", events, budget)
    reader = router.for_role("scientific_extract")
    synthesis = router.for_role("scientific_synthesis")
    assert reader.model == "openai/gpt-oss-20b"
    assert reader.options["max_completion_tokens"] == 1536
    assert reader.options["reasoning_effort"] == "low"
    assert synthesis.options["max_completion_tokens"] == 2048
    assert synthesis.model == "openai/gpt-oss-120b"
    assert reader.options["budget"] is synthesis.options["budget"] is budget
    assert reader.options["quota"] is synthesis.options["quota"] is worker.quota
    reader.options["on_quota"]({"wait_seconds": 0})
    assert events.items[-1]["agent"] == "scientific_review"
