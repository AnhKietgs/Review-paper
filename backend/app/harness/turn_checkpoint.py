"""Save reusable model steps without committing partial worker mutations."""

from copy import deepcopy

from app.domain.policies.tool_policy import TOOL_ALLOWLIST
from app.harness.evidence import span_source
from app.harness.memory import RunMemory
from app.harness.state import RunState


def save_progress(memory: RunMemory, state: RunState) -> None:
    """Keep pre-worker queues/counters; persist only reusable steps and usage."""
    if state.turn_progress is None:
        return
    checkpoint = memory.load(state.run_id)
    checkpoint.turn_progress = state.turn_progress.model_copy(deep=True)
    checkpoint.call_counts = dict(state.call_counts)
    memory.save(checkpoint)


def reusable_context(state, role, source_ids, catalog) -> dict | None:
    """Reuse inputs only while original source permissions/content still hold."""
    progress = state.turn_progress
    if (
        progress is None or progress.context is None
        or progress.context_role != role or progress.source_ids != source_ids
    ):
        return None
    if (
        progress.context["scope"] != state.scope.model_dump()
        or "read_chunks" not in TOOL_ALLOWLIST.get(role, set())
    ):
        return None
    for saved in progress.context["chunks"]:
        current = catalog.chunk(saved["id"])
        if current is None or not catalog.is_active(current["paper_id"]):
            return None
        if (
            not state.scope.permits(
                current["paper_id"], current["content_version"],
            )
            or (role == "scientific_review"
                and current["paper_id"] != state.scope.main_paper_id)
            or saved != (span_source(current) if "spans" in saved else current)
        ):
            return None
    return deepcopy(progress.context)


def turn_budget_exhausted(state: RunState) -> bool:
    """An admitted unfinished turn can finish without spending a second turn."""
    if state.turn_progress is not None:
        return False
    if state.turn_count >= state.max_turns:
        return True
    return (
        state.batch_count >= state.max_batches and bool(state.remaining_chunk_ids)
        and not state.current_batch_ids and not state.pending_findings
    )
