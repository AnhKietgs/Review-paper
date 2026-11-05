"""Background queue, restart recovery and checkpoint resume."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.ports import LLMFailure, RateLimitPause
from app.harness.memory import RunMemory
from app.infrastructure.persistence.unit_of_work import UnitOfWork
from app.harness.runner import AgentRunner
from app.workers.run_worker import RunWorker


def test_oversized_context_failure_can_resume_its_existing_checkpoint(
    api_client, review_seed, monkeypatch,
):
    review = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    worker = RunWorker()
    worker.tick()
    original_turn = AgentRunner.run_turn

    def oversized(_self, _state):
        raise LLMFailure("quota_request_too_large")

    monkeypatch.setattr(AgentRunner, "run_turn", oversized)
    worker.tick()
    failed = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert failed["status"] == "failed"
    assert failed["step_count"] == 1
    resumed = api_client.post(f"/api/v1/runs/{accepted['run_id']}/resume")
    assert resumed.status_code == 202
    assert resumed.json()["run_id"] == accepted["run_id"]
    assert resumed.json()["review_id"] == accepted["review_id"]
    monkeypatch.setattr(AgentRunner, "run_turn", original_turn)
    for _ in range(20):
        worker.tick()
    result = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert result["status"] == "completed"


def test_queue_restart_resume_and_no_duplicate_findings(api_client, review_seed):
    first = review_seed()
    second = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{first['id']}/runs")
    assert accepted.status_code == 202, accepted.text
    run_id = accepted.json()["run_id"]
    revision_id = accepted.json()["review_id"]
    assert revision_id != first["id"]
    next_run = api_client.post(f"/api/v1/reviews/{second['id']}/runs").json()["run_id"]
    worker = RunWorker()
    worker.tick()
    assert api_client.get(f"/api/v1/runs/{run_id}").json()["status"] == "running"
    assert api_client.get(f"/api/v1/runs/{next_run}").json()["status"] == "queued"
    before = api_client.get(f"/api/v1/runs/{run_id}").json()["step_count"]
    worker.recover_interrupted()
    assert api_client.get(f"/api/v1/runs/{run_id}").json()["status"] == "interrupted"
    assert api_client.post(f"/api/v1/runs/{run_id}/resume").status_code == 202
    assert api_client.post(f"/api/v1/runs/{run_id}/resume").status_code == 409
    for _ in range(40):
        worker.tick()
    result = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert result["status"] == "completed"
    assert result["step_count"] > before
    assert api_client.post(f"/api/v1/runs/{run_id}/resume").status_code == 409
    events = api_client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
    findings = api_client.get(f"/api/v1/reviews/{revision_id}").json()["findings"]
    assert len({finding["id"] for finding in findings}) == len(findings)
    assert api_client.get(f"/api/v1/reviews/{first['id']}").json()["findings"] == []


def test_concurrent_start_for_same_review_is_serialized(api_client, review_seed):
    """Concurrent submissions cannot create duplicate active review runs."""
    review = review_seed(False)
    path = f"/api/v1/reviews/{review['id']}/runs"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: api_client.post(path), range(2)))
    assert sorted(response.status_code for response in responses) == [202, 409]
    accepted = next(
        response.json() for response in responses if response.status_code == 202
    )
    assert (
        api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()["status"]
        == "queued"
    )


@pytest.mark.parametrize("pause_seconds", [60, 381])
def test_rate_limit_cools_down_and_continues_same_checkpoint(
    api_client, review_seed, monkeypatch, pause_seconds
):
    review = review_seed(False)
    run_id = api_client.post(
        f"/api/v1/reviews/{review['id']}/runs"
    ).json()["run_id"]
    original_turn = AgentRunner.run_turn
    attempts = []

    def limited_once(self, state):
        attempts.append(1)
        if len(attempts) == 1:
            raise RateLimitPause(pause_seconds)
        return original_turn(self, state)

    monkeypatch.setattr(AgentRunner, "run_turn", limited_once)
    worker = RunWorker()
    assert worker.tick()
    paused = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert paused["status"] == "running"
    assert paused["step_count"] == 0
    assert paused["error_code"] is None
    assert paused["cooldown_until"] is not None
    deadline = datetime.fromisoformat(paused["cooldown_until"].replace("Z", "+00:00"))
    assert (deadline - datetime.now(timezone.utc)).total_seconds() > pause_seconds - 5
    assert not worker.tick()
    assert len(attempts) == 1
    worker.recover_interrupted()
    assert api_client.get(f"/api/v1/runs/{run_id}").json()["status"] == "running"

    with UnitOfWork() as unit:
        state = RunMemory(unit.session).load(run_id)
        state.cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        RunMemory(unit.session).save(state)
    assert worker.tick()
    resumed = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert resumed["step_count"] == 1
    assert resumed["cooldown_until"] is None
    events = api_client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    assert any(item["action"] == "provider_cooldown" for item in events)
