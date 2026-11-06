"""Public measured progress; transient activity for the single local worker."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock

from app.harness.state import RunState

ACTION_AGENTS = {
    "analyze": "scientific_review", "compare": "related_work",
    "verify": "evidence_verifier", "repair": "scientific_review",
    "audit_omission": "evidence_verifier", "next_batch": "harness",
    "finish": "harness",
}


def build_activity(state: RunState, status: str) -> dict:
    """Project counts only; paper coverage is not overall review completion."""
    action = state.turn_progress.action.action if state.turn_progress else None
    phase = action or "preparing"
    if status != "running":
        phase = status
    elif state.cooldown_until is not None:
        phase = "waiting_quota"
    audits = state.omission_audits
    cursor = audits[0]["checked"] if audits else 0
    return {
        "phase": phase, "resume_action": action,
        "agent": ACTION_AGENTS.get(action), "source": "checkpoint",
        "updated_at": None,
        "retry_at": (
            state.cooldown_until.isoformat()
            if phase == "waiting_quota" else None
        ),
        "work": {
            "paper_read": {
                "done": len(set(state.processed_chunk_ids)),
                "total": len(set(
                    state.processed_chunk_ids + state.remaining_chunk_ids
                    + state.current_batch_ids
                )),
            },
            "references": {
                "done": len(state.reference_assessments),
                "total": len(state.scope.reference_versions),
            },
            "findings": {
                "total": len({
                    item["id"] for item in state.findings + state.pending_findings
                }),
                "pending_verification": len(state.pending_findings),
                "pending_repairs": len(state.repair_queue),
                "repair_attempts": state.repair_count,
            },
            "omission_audit": {
                "topics_pending": len(audits),
                "group_topics": min(10, sum(
                    item["checked"] == cursor for item in audits
                )),
                "checked_chunks": cursor,
                "total_chunks": len(state.processed_chunk_ids),
            },
        },
    }


class LiveActivity:
    """Thread-safe metadata only; never store document text or model context."""

    def __init__(self):
        self._lock = Lock()
        self._items: dict[str, dict] = {}

    def publish(self, state: RunState, event=None) -> None:
        """Publish the worker's current phase while a provider call is in flight."""
        value = build_activity(state, state.status)
        value["source"] = "live"
        now = datetime.now(timezone.utc)
        value["updated_at"] = now.isoformat()
        if event is None or (
            event.agent == "supervisor"
            and event.action in {"agent_started", "quota_reserved"}
        ):
            value["phase"] = "planning" if not state.turn_progress else value["phase"]
        if event is not None:
            value["agent"] = event.agent
            if event.action in {"quota_wait", "provider_retry"}:
                wait = event.payload.get("wait_seconds", 0)
                if wait > 0:
                    value["phase"] = "waiting_quota"
                    value["retry_at"] = (now + timedelta(seconds=wait)).isoformat()
        with self._lock:
            self._items[state.run_id] = value

    def get(self, run_id: str) -> dict | None:
        """Return isolated public metadata to HTTP readers."""
        with self._lock:
            return deepcopy(self._items.get(run_id))

    def clear(self, run_id: str) -> None:
        """Do not leave a completed or failed tick displayed as active."""
        with self._lock:
            self._items.pop(run_id, None)


LIVE_ACTIVITY = LiveActivity()


def get_activity(state: RunState, status: str) -> dict:
    """Durable lifecycle/deadline always overrides transient live activity."""
    if status == "running" and (
        state.cooldown_until is None
        or state.cooldown_until <= datetime.now(timezone.utc)
    ):
        live = LIVE_ACTIVITY.get(state.run_id)
        if live is not None:
            return live
    return build_activity(state, status)
