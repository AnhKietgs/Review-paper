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


def test_only_new_full_groq_reviews_enable_two_phase_policy(api_client, review_seed, monkeypatch):
    review = review_seed(False)
    monkeypatch.setenv("DEMO_LLM_MODE", "groq")
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    with UnitOfWork() as unit:
        saved = RunMemory(unit.session).load(accepted["run_id"])
        assert saved.two_phase_review and saved.efficient_review
        assert saved.max_repairs == 2 and saved.max_omission_topics == 2
        assert saved.read_notes == [] and not saved.scientific_synthesized
    api_client.post(f"/api/v1/runs/{accepted['run_id']}/cancel")
    verify = api_client.post(f"/api/v1/reviews/{review['id']}/runs", json={"mode": "verify"}).json()
    with UnitOfWork() as unit:
        assert not RunMemory(unit.session).load(verify["run_id"]).two_phase_review


def budget_stopped(api_client, review_seed, limit=50000, spent=45917):
    from app.harness.state import TurnProgress

    accepted = api_client.post(
        f"/api/v1/reviews/{review_seed(False)['id']}/runs"
    ).json()
    with UnitOfWork() as unit:
        row = unit.session.get(RunRow, accepted["run_id"])
        row.status, row.error_code = "incomplete", "review_token_budget_exhausted"
        row.usage = {"calls": 20, "tokens": spent}
        state = RunMemory(unit.session).load(row.id)
        state.status, state.error_code = row.status, row.error_code
        state.token_budget, state.token_spent = limit, spent
        state.turn_progress = TurnProgress(
            action={"action": "verify", "reason": "Saved task"},
            work_contexts=[{"part": 1}, {"part": 2}],
            work_outputs=[{"assessments": []}],
        )
        RunMemory(unit.session).save(state)
    return accepted


def test_explicit_extension_resumes_same_checkpoint_without_resetting_spend(
    api_client, review_seed,
):
    accepted = budget_stopped(api_client, review_seed)
    url = f"/api/v1/runs/{accepted['run_id']}/resume"
    assert api_client.post(url).status_code == 409
    resumed = api_client.post(url, json={"token_budget": 80000})
    assert resumed.status_code == 202, resumed.text
    assert resumed.json()["run_id"] == accepted["run_id"]
    assert resumed.json()["review_id"] == accepted["review_id"]
    actual = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert actual["token_budget"] == {"limit": 80000, "spent": 45917, "remaining": 34083}
    assert actual["usage"] == {"calls": 20, "tokens": 45917}
    assert actual["status"] == "queued"
    with UnitOfWork() as unit:
        saved = RunMemory(unit.session).load(accepted["run_id"])
        assert saved.turn_progress.action.action == "verify"
        assert len(saved.turn_progress.work_contexts) == 2
        assert len(saved.turn_progress.work_outputs) == 1
    assert api_client.post(url, json={"token_budget": 80000}).status_code == 409
    events = api_client.get(f"/api/v1/runs/{accepted['run_id']}/events").json()["items"]
    extension = next(e for e in events if e["action"] == "review_budget_extended")
    assert extension["payload"] == {"previous_limit": 50000, "new_limit": 80000,
                                    "spent": 45917}


@pytest.mark.parametrize("limit,spent,requested", [
    (90000, 65000, 150000), (50000, 71000, 90000),
])
def test_budget_extension_cannot_reset_or_underfund_existing_usage(
    api_client, review_seed, limit, spent, requested,
):
    accepted = budget_stopped(api_client, review_seed, limit, spent)
    response = api_client.post(f"/api/v1/runs/{accepted['run_id']}/resume",
                               json={"token_budget": requested})
    assert response.status_code == 409
    actual = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert actual["status"] == "incomplete"
    assert actual["token_budget"]["limit"] == limit
    assert actual["token_budget"]["spent"] == spent


@pytest.mark.parametrize("status", ["queued", "running", "cancelled", "completed"])
def test_budget_extension_rejects_non_budget_stopped_runs(
    api_client, review_seed, status,
):
    accepted = budget_stopped(api_client, review_seed)
    with UnitOfWork() as unit:
        unit.session.get(RunRow, accepted["run_id"]).status = status
    response = api_client.post(f"/api/v1/runs/{accepted['run_id']}/resume",
                               json={"token_budget": 90000})
    assert response.status_code == 409
    actual = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert actual["status"] == status
    assert actual["token_budget"]["limit"] == 50000


def test_budget_extension_has_strict_body_and_serializes_duplicate_requests(
    api_client, review_seed,
):
    accepted = budget_stopped(api_client, review_seed)
    url = f"/api/v1/runs/{accepted['run_id']}/resume"
    assert api_client.post(url, json={"token_budget": 160000}).status_code == 422
    assert api_client.post(url, json={"reset_spend": True}).status_code == 422
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _: api_client.post(url, json={"token_budget": 80000}).status_code,
            range(2),
        ))
    assert sorted(results) == [202, 409]
    actual = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert actual["token_budget"] == {"limit": 80000, "spent": 45917, "remaining": 34083}


def test_budget_extension_does_not_restart_a_deleted_review(api_client, review_seed):
    accepted = budget_stopped(api_client, review_seed)
    assert api_client.delete(f"/api/v1/reviews/{accepted['review_id']}").status_code == 204
    response = api_client.post(f"/api/v1/runs/{accepted['run_id']}/resume",
                               json={"token_budget": 80000})
    assert response.status_code == 404
    actual = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert actual["status"] == "incomplete"
    assert actual["token_budget"]["limit"] == 50000


def test_budget_extension_conflicts_with_a_newer_active_sibling(api_client, review_seed):
    accepted = budget_stopped(api_client, review_seed)
    with UnitOfWork() as unit:
        source = unit.session.get(RunRow, accepted["run_id"]).requested_review_id
    newer = api_client.post(f"/api/v1/reviews/{source}/runs")
    assert newer.status_code == 202
    response = api_client.post(f"/api/v1/runs/{accepted['run_id']}/resume",
                               json={"token_budget": 80000})
    assert response.status_code == 409
    actual = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert actual["status"] == "incomplete"
    assert actual["token_budget"]["limit"] == 50000


def test_legacy_turn_finishes_before_enabling_efficient_schedule(
    api_client, review_seed, monkeypatch,
):
    from app.harness.state import TurnProgress

    review = review_seed()
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    worker = RunWorker()
    worker.tick()
    worker.tick()
    with UnitOfWork() as unit:
        state = RunMemory(unit.session).load(accepted["run_id"])
        assert state.pending_findings
        state.llm_mode = "groq"
        state.efficient_review = False
        state.turn_progress = TurnProgress(action={
            "action": "verify", "reason": "Previously admitted verification",
        })
        RunMemory(unit.session).save(state)
    monkeypatch.setenv("GROQ_API_KEY", "offline-only")
    monkeypatch.setattr(RunWorker, "_create_groq_router", lambda *_args: FixtureClient())
    worker.tick()
    after = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert after["efficient_review"] is False
    assert after["call_counts"]["evidence_verifier"] == 1
    worker.tick()
    upgraded = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert upgraded["efficient_review"] is True
    assert upgraded["processed"] == after["processed"]


@pytest.mark.parametrize("checkpoint_spent,reported_spent", [(49999, 0), (0, 49999)])
def test_review_budget_stop_preserves_checkpoint_and_cannot_reset_by_resume(
    api_client, review_seed, monkeypatch, checkpoint_spent, reported_spent,
):
    from app.agents.schemas import AgentAction
    from app.harness.state import TurnProgress
    from app.infrastructure.groq.client import GroqClient

    monkeypatch.setenv("REVIEW_TOKEN_BUDGET", "50000")
    review = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    worker = RunWorker()
    worker.tick()
    with UnitOfWork() as unit:
        state = RunMemory(unit.session).load(accepted["run_id"])
        state.llm_mode = "groq"
        state.token_spent = checkpoint_spent
        unit.session.get(RunRow, accepted["run_id"]).usage = {
            "tokens": reported_spent, "calls": 0,
        }
        state.turn_progress = TurnProgress(action=AgentAction(
            action="analyze", reason="Continue selected work",
        ))
        RunMemory(unit.session).save(state)
        original_batch = list(state.current_batch_ids)
    calls = []

    def client(*args, **kwargs):
        return GroqClient(*args, **kwargs, completion=lambda **_: calls.append(1))

    monkeypatch.setenv("GROQ_API_KEY", "fake-for-offline-test")
    monkeypatch.setattr("app.workers.run_worker.GroqClient", client)
    worker.tick()
    result = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert result["status"] == "incomplete", result
    assert result["error_code"] == "review_token_budget_exhausted"
    assert result["token_budget"] == {"limit": 50000, "spent": 49999, "remaining": 1}
    assert calls == []
    assert api_client.post(f"/api/v1/runs/{accepted['run_id']}/resume").status_code == 409
    with UnitOfWork() as unit:
        saved = RunMemory(unit.session).load(accepted["run_id"])
        assert saved.current_batch_ids == original_batch
        assert saved.turn_progress.action.action == "analyze"
    assert worker.tick() is False


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


def test_restart_stops_legacy_over_budget_run_even_during_quota_cooldown(
    api_client, review_seed,
):
    review = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    with UnitOfWork() as unit:
        row = unit.session.get(RunRow, accepted["run_id"])
        row.status = "running"
        row.usage = {"calls": 20, "tokens": 50001}
        state = RunMemory(unit.session).load(row.id)
        state.llm_mode = "groq"
        state.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
        RunMemory(unit.session).save(state)
    RunWorker.recover_interrupted()
    result = api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert result["status"] == "incomplete"
    assert result["error_code"] == "review_token_budget_exhausted"
    assert result["token_budget"]["spent"] == 50001
    assert result["cooldown_until"] is None
    assert result["remaining"] > 0


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


@pytest.mark.parametrize("code", [
    "provider_unavailable", "provider_timeout", "provider_connection_error",
    "invalid_model_output",
])
def test_provider_failure_resumes_existing_successful_subtask_checkpoint(
    api_client, review_seed, code,
):
    from app.harness.state import TurnProgress

    review = review_seed(False)
    accepted = api_client.post(f"/api/v1/reviews/{review['id']}/runs").json()
    run_id = accepted["run_id"]
    with UnitOfWork() as unit:
        row = unit.session.get(RunRow, run_id)
        row.status, row.error_code = "failed", code
        state = RunMemory(unit.session).load(run_id)
        state.status, state.error_code = "failed", code
        state.turn_progress = TurnProgress(
            action={"action": "verify", "reason": "Resume"},
            work_contexts=[{"part": i} for i in range(3)],
            work_outputs=[{"assessments": []}],
        )
        RunMemory(unit.session).save(state)
    result = api_client.post(f"/api/v1/runs/{run_id}/resume")
    assert result.status_code == 202
    assert result.json()["run_id"] == run_id
    assert result.json()["review_id"] == accepted["review_id"]
    with UnitOfWork() as unit:
        saved = RunMemory(unit.session).load(run_id)
        assert len(saved.turn_progress.work_outputs) == 1
        assert len(saved.turn_progress.work_contexts) == 3
        assert saved.turn_progress.action.action == "verify"
