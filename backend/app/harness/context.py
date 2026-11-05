"""Explicit context assembly from approved tool results."""

from app.harness.state import RunState
from app.harness.evidence import span_source


class ContextBuilder:
    """Build only the context needed for the selected role."""

    def build(
        self, state: RunState, chunks: list[dict], criteria: list[dict],
        include_spans: bool = False,
    ) -> dict:
        """Provide bounded source content and public progress metadata."""
        return {
            "scope": state.scope.model_dump(),
            "progress": {
                "remaining": len(state.remaining_chunk_ids),
                "processed": len(state.processed_chunk_ids),
                "batch_count": state.batch_count,
                "turn_count": state.turn_count,
            },
            "chunks": (
                [span_source(chunk) for chunk in chunks] if include_spans else chunks
            ),
            "criteria": criteria,
            "pending_findings": state.pending_findings,
            "reference_assessments": state.reference_assessments,
        }
