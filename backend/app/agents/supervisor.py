"""Supervisor suggestions constrained by deterministic eligibility."""

from app.agents.schemas import AgentAction
from app.harness.state import RunState


def eligible_actions(state: RunState) -> list[str]:
    """Return legal scheduling choices from current durable progress."""
    if state.pending_findings:
        return ["verify"]
    if state.repair_queue:
        return ["repair"]
    if state.current_batch_ids:
        return ["analyze"]
    if state.remaining_chunk_ids:
        return ["next_batch"]
    if set(state.scope.reference_versions) - set(state.reference_assessments):
        return ["compare"]
    return ["audit_omission" if state.omission_audits else "finish"]


class Supervisor:
    """Ask the controller model for the next bounded action."""

    def __init__(self, graph):
        self.graph = graph

    def decide(self, state: RunState) -> AgentAction:
        """Expose scheduling metadata without sending the whole document."""
        context = {
            "allowed_actions": eligible_actions(state),
            "remaining_chunks": len(state.remaining_chunk_ids),
            "current_batch": state.current_batch_ids,
            "pending_findings": len(state.pending_findings),
            "repair_queue": len(state.repair_queue),
            "unassessed_references": sorted(
                set(state.scope.reference_versions) - set(state.reference_assessments)
            ),
            "turn": state.turn_count,
        }
        return AgentAction.model_validate(
            self.graph.invoke({"context": context})["output"]
        )
