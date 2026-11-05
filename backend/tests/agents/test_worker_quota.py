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
    assert len(clients) == 8
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
