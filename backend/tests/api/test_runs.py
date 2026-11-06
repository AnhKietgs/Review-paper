"""Background queue, restart recovery and checkpoint resume."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.ports import LLMFailure, RateLimitPause
from app.harness.memory import RunMemory
from app.infrastructure.persistence.unit_of_work import UnitOfWork
from app.infrastructure.persistence.orm_models import RunRow
from app.harness.runner import AgentRunner
from app.workers.run_worker import RunWorker
from app.agents.schemas import AgentAction, ScientificOutput
from app.infrastructure.groq.fixture_client import FixtureClient


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


def test_worker_cooldown_persists_decision_and_only_retries_worker(
    api_client, review_seed, monkeypatch,
):
    review = review_seed(False)
    run_id = api_client.post(
        f"/api/v1/reviews/{review['id']}/runs"
    ).json()["run_id"]
    worker = RunWorker()
    worker.tick()  # Reserve the main document batch first.
    original_generate = FixtureClient.generate_json
    calls = {"supervisor": 0, "worker": 0}

    def limited_once(self, messages, schema):
        if schema is AgentAction:
            calls["supervisor"] += 1
        if schema is ScientificOutput:
            calls["worker"] += 1
            if calls["worker"] == 1:
                raise RateLimitPause(60)
        return original_generate(self, messages, schema)

    monkeypatch.setattr(FixtureClient, "generate_json", limited_once)
    assert worker.tick()
    with UnitOfWork() as unit:
        state = RunMemory(unit.session).load(run_id)
        assert state.turn_progress.action.action == "analyze"
        assert state.turn_progress.context is not None
        assert state.turn_count == 2
        assert state.processed_chunk_ids == []
        state.cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        RunMemory(unit.session).save(state)
    assert RunWorker().tick()  # Fresh worker restores the serialized progress.
    assert calls == {"supervisor": 1, "worker": 2}
    with UnitOfWork() as unit:
        state = RunMemory(unit.session).load(run_id)
        assert state.turn_progress is None
        assert state.turn_count == 2
        assert len(state.processed_chunk_ids) == 1
    events = api_client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    assert any(e["action"] == "decision_reused" for e in events)
    assert any(e["action"] == "context_reused" for e in events)


def test_current_work_is_visible_during_an_unfinished_model_call(
    api_client, review_seed, monkeypatch,
):
    review = review_seed(False)
    run_id = api_client.post(
        f"/api/v1/reviews/{review['id']}/runs"
    ).json()["run_id"]
    worker = RunWorker()
    worker.tick()
    started, release = Event(), Event()
    generate = FixtureClient.generate_json

    def slow_model(self, messages, schema):
        if schema is ScientificOutput:
            started.set()
            assert release.wait(10)
        return generate(self, messages, schema)

    monkeypatch.setattr(FixtureClient, "generate_json", slow_model)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(worker.tick)
        try:
            assert started.wait(10)
            response = api_client.get(f"/api/v1/runs/{run_id}")
            activity = response.json()["activity"]
            assert activity["source"] == "live"
            assert activity["phase"] == "analyze"
            assert activity["agent"] == "scientific_review"
            assert activity["work"]["paper_read"] == {"done": 0, "total": 1}
            assert "context" not in activity
            assert "chunks" not in activity
        finally:
            release.set()
        assert task.result(timeout=10)
    activity = api_client.get(f"/api/v1/runs/{run_id}").json()["activity"]
    assert activity["source"] == "checkpoint"
    assert activity["phase"] == "preparing"


@pytest.mark.parametrize("status", ["queued", "running", "interrupted", "failed"])
def test_cancel_keeps_review_and_checkpoint_and_is_idempotent(
    api_client, review_seed, status,
):
    review = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    run_id = accepted["run_id"]
    with UnitOfWork() as unit:
        row = unit.session.get(RunRow, run_id)
        row.status = status
        state = RunMemory(unit.session).load(run_id)
        state.status = status
        state.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
        before_remaining = list(state.remaining_chunk_ids)
        RunMemory(unit.session).save(state)
    for _ in range(2):
        result = api_client.post(f"/api/v1/runs/{run_id}/cancel")
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "cancelled"
    result = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert result["status"] == "cancelled"
    assert result["cooldown_until"] is None
    assert result["activity"]["phase"] == "cancelled"
    assert api_client.get(f"/api/v1/reviews/{accepted['review_id']}").status_code == 200
    assert api_client.post(f"/api/v1/runs/{run_id}/resume").status_code == 409
    assert not RunWorker().tick()
    with UnitOfWork() as unit:
        state = RunMemory(unit.session).load(run_id)
        assert state.status == "cancelled"
        assert state.remaining_chunk_ids == before_remaining
    events = api_client.get(f"/api/v1/runs/{run_id}/events").json()["items"]
    assert sum(e["action"] == "run_cancelled" for e in events) == 1


def test_cancel_rejects_missing_or_completed_run(api_client, review_seed):
    assert api_client.post("/api/v1/runs/missing/cancel").status_code == 404
    review = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    worker = RunWorker()
    for _ in range(10):
        worker.tick()
    assert api_client.post(
        f"/api/v1/runs/{accepted['run_id']}/cancel"
    ).status_code == 409


def test_late_worker_result_cannot_overwrite_user_cancellation(
    api_client, review_seed, monkeypatch,
):
    review = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    run_id = accepted["run_id"]
    worker = RunWorker()
    worker.tick()
    started, release = Event(), Event()
    generate = FixtureClient.generate_json

    def slow_model(self, messages, schema):
        if schema is ScientificOutput:
            started.set()
            assert release.wait(10)
        return generate(self, messages, schema)

    monkeypatch.setattr(FixtureClient, "generate_json", slow_model)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(worker.tick)
        try:
            assert started.wait(10)
            assert api_client.post(f"/api/v1/runs/{run_id}/cancel").status_code == 200
        finally:
            release.set()
        assert task.result(timeout=10)
    result = api_client.get(f"/api/v1/runs/{run_id}").json()
    assert result["status"] == "cancelled"
    assert result["processed"] == 0
    assert api_client.get(
        f"/api/v1/reviews/{accepted['review_id']}"
    ).json()["findings"] == []


def test_persist_and_cancel_serialize_before_reading_run_status(
    api_client, review_seed, monkeypatch,
):
    from app.harness.events import RunEventRecorder

    review = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    run_id = accepted["run_id"]
    RunWorker().tick()
    with UnitOfWork() as unit:
        state = RunMemory(unit.session).load(run_id)
    original_steps = state.turn_count
    state.turn_count += 1
    read, release, cancelled = Event(), Event(), Event()
    persisting_thread = []
    original_get = Session.get

    def held_get(self, entity, ident, *args, **kwargs):
        result = original_get(self, entity, ident, *args, **kwargs)
        if entity is RunRow and ident == run_id and get_ident() in persisting_thread:
            read.set()
            assert release.wait(10)
        return result

    def persist():
        persisting_thread.append(get_ident())
        RunWorker._persist(state, RunEventRecorder(), {}, original_steps)

    def cancel():
        result = api_client.post(f"/api/v1/runs/{run_id}/cancel")
        cancelled.set()
        return result

    monkeypatch.setattr(Session, "get", held_get)
    with ThreadPoolExecutor(max_workers=2) as pool:
        saving = pool.submit(persist)
        assert read.wait(10)
        cancelling = pool.submit(cancel)
        try:
            assert not cancelled.wait(1)
        finally:
            release.set()
        saving.result(timeout=10)
        assert cancelling.result(timeout=10).status_code == 200
    assert api_client.get(f"/api/v1/runs/{run_id}").json()["status"] == "cancelled"
