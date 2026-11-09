"""Measured work, live activity and safe checkpoint fallback."""

from datetime import datetime, timedelta, timezone

from app.agents.schemas import AgentAction
from app.harness.activity import LIVE_ACTIVITY, build_activity, get_activity
from app.harness.events import RunEventInput
from app.harness.state import RunScope, RunState, TurnProgress


def state():
    return RunState(
        run_id="activity-test", review_id="review",
        scope=RunScope(
            main_paper_id="paper", main_version=1, reference_versions={"ref": 1},
            rubric_id="rubric", rubric_version=1,
        ),
        processed_chunk_ids=["a", "b"], remaining_chunk_ids=["c", "d"],
        current_batch_ids=["c"], pending_findings=[{"id": "one"}],
        findings=[{"id": "two", "status": "unsupported"}],
        repair_queue=[{"finding_id": "two"}], repair_count=2,
        omission_audits=[{"checked": 1}, {"checked": 1}],
        turn_progress=TurnProgress(action=AgentAction(action="repair", reason="Fix")),
    )


def test_checkpoint_reports_work_counts_without_fake_overall_percentage():
    activity = build_activity(state(), "running")
    assert activity["phase"] == "repair"
    assert activity["work"]["paper_read"] == {"done": 2, "total": 4}
    assert activity["work"]["findings"] == {
        "total": 2, "pending_verification": 1, "pending_repairs": 1,
        "repair_attempts": 2,
    }
    assert activity["work"]["omission_audit"]["checked_chunks"] == 1
    assert "percent" not in activity
    assert "context" not in activity


def test_quota_state_keeps_resume_action_and_deadline():
    saved = state()
    saved.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=60)
    activity = build_activity(saved, "running")
    assert activity["phase"] == "waiting_quota"
    assert activity["resume_action"] == "repair"
    assert activity["retry_at"] == saved.cooldown_until.isoformat()
    assert build_activity(saved, "cancelled")["phase"] == "cancelled"


def test_two_phase_activity_distinguishes_reading_and_synthesis_without_notes_text():
    saved = state()
    saved.two_phase_review = True
    saved.read_notes = [{"text": "private document note"}]
    saved.turn_progress = TurnProgress(action=AgentAction(action="analyze", reason="Read"))
    public = build_activity(saved, "running")
    assert public["phase"] == "extract"
    assert public["work"]["scientific"]["note_count"] == 1
    assert "private document note" not in str(public)
    saved.turn_progress.action = AgentAction(action="synthesize", reason="Review")
    assert build_activity(saved, "running")["phase"] == "synthesize"


def test_live_activity_is_safe_and_cannot_override_terminal_or_cooldown_state():
    saved = state()
    try:
        LIVE_ACTIVITY.publish(saved, RunEventInput(
            agent="evidence_verifier", action="agent_started",
        ))
        public = get_activity(saved, "running")
        assert public["source"] == "live"
        assert public["phase"] == "repair"
        assert public["agent"] == "evidence_verifier"
        public["work"]["paper_read"]["done"] = 999
        assert get_activity(saved, "running")["work"]["paper_read"]["done"] == 2
        assert get_activity(saved, "failed")["phase"] == "failed"
        saved.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=60)
        assert get_activity(saved, "running")["phase"] == "waiting_quota"
    finally:
        LIVE_ACTIVITY.clear(saved.run_id)
    assert get_activity(state(), "running")["source"] == "checkpoint"


def test_quota_wait_inside_provider_call_is_visible_before_tick_finishes():
    saved = state()
    try:
        LIVE_ACTIVITY.publish(saved, RunEventInput(
            agent="scientific_review", action="quota_wait",
            payload={"wait_seconds": 61},
        ))
        public = get_activity(saved, "running")
        assert public["phase"] == "waiting_quota"
        assert public["retry_at"] is not None
        assert public["resume_action"] == "repair"
    finally:
        LIVE_ACTIVITY.clear(saved.run_id)


def test_resumed_live_work_overrides_expired_checkpoint_cooldown():
    saved = state()
    try:
        LIVE_ACTIVITY.publish(saved, RunEventInput(
            agent="scientific_review", action="agent_started",
        ))
        saved.cooldown_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert get_activity(saved, "running")["phase"] == "repair"
    finally:
        LIVE_ACTIVITY.clear(saved.run_id)


def test_supervisor_quota_reservation_keeps_planning_phase():
    saved = state()
    saved.turn_progress = None
    try:
        LIVE_ACTIVITY.publish(saved, RunEventInput(
            agent="supervisor", action="quota_reserved", payload={"wait_seconds": 0},
        ))
        assert get_activity(saved, "running")["phase"] == "planning"
    finally:
        LIVE_ACTIVITY.clear(saved.run_id)
