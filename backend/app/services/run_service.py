"""Start, inspect and resume durable review executions."""

from uuid import uuid4
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.schemas.runs import RunAccepted
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.harness.events import RunEventInput, RunEventRecorder
from app.harness.activity import get_activity
from app.harness.memory import RunMemory
from app.harness.state import RunScope, RunState
from app.infrastructure.persistence.orm_models import RunRow
from app.infrastructure.persistence.run_repository import SqlRunRepository
from app.infrastructure.persistence.source_catalog import SqlSourceCatalog
from app.services.review_service import ReviewService


class RunService:
    """Application facade for the background harness."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = SqlRunRepository(session)

    def start(self, review_id: str, mode: str = "review") -> RunAccepted:
        """Freeze a new revision before adding it to the single-worker queue."""
        # Serialize the active-run check with its insert on SQLite.
        self.session.execute(text("BEGIN IMMEDIATE"))
        reviews = ReviewService(self.session)
        source = reviews.get(review_id)
        active = self.session.scalar(
            select(RunRow).where(
                RunRow.requested_review_id == review_id,
                RunRow.status.in_(["queued", "running", "interrupted"]),
            )
        )
        if active:
            raise ConflictError(
                "run_active", "This review already has an unfinished run"
            )
        catalog = SqlSourceCatalog(self.session)
        if not catalog.is_active(source.paper_id):
            raise NotFoundError("paper_missing", "Main paper is unavailable")
        revision = reviews.new_revision(review_id, lock=False)
        scope = RunScope(
            main_paper_id=revision.paper_id,
            main_version=revision.paper_content_version,
            reference_versions={
                item.paper_id: item.paper_content_version
                for item in revision.references
            },
            rubric_id=revision.rubric_id,
            rubric_version=revision.rubric_version,
        )
        chunk_ids = [
            item["id"]
            for item in catalog.chunks(scope.main_paper_id, scope.main_version)
        ]
        run = RunRow(
            id=str(uuid4()),
            review_id=revision.id,
            requested_review_id=review_id,
            status="queued",
            step_count=0,
            usage={},
        )
        self.session.add(run)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(
                "run_active", "This review already has an unfinished run"
            ) from exc
        state = RunState(
            run_id=run.id,
            review_id=revision.id,
            scope=scope,
            remaining_chunk_ids=chunk_ids,
            llm_mode=Settings.from_env().demo_llm_mode,
        )
        if mode == "verify":
            state.remaining_chunk_ids = []
            state.processed_chunk_ids = chunk_ids
            state.analysis = dict(revision.analysis.get("sections", {}))
            state.reference_assessments = dict(revision.analysis.get("references", {}))
            for finding in revision.findings:
                draft = finding.model_dump(exclude={"status", "verdict"})
                if finding.status == "pending":
                    if finding.kind == "omission":
                        state.omission_audits.append(
                            {"finding": draft, "checked": 0, "ambiguous": False}
                        )
                    else:
                        state.pending_findings.append(draft)
                else:
                    state.findings.append(finding.model_dump())
            for paper_id in scope.reference_versions:
                state.reference_assessments.setdefault(
                    paper_id,
                    {
                        "status": "not_assessed",
                        "reason": "Verification-only run",
                        "chunk_ids": [],
                    },
                )
        else:
            for finding in reviews.repository.findings(revision.id):
                self.session.delete(finding)
            row = reviews.repository.get(revision.id)
            row.analysis = {}
            row.summary = ""
        RunMemory(self.session).save(state)
        RunEventRecorder(self.session).append(
            run.id,
            RunEventInput(
                agent="harness",
                action="run_queued",
                output_summary=f"New revision; mode={mode}",
            ),
        )
        return RunAccepted(run_id=run.id, review_id=revision.id, status=run.status)

    def get(self, run_id: str) -> dict:
        """Expose durable progress without raw prompts or credentials."""
        row = self.repository.get(run_id)
        if row is None:
            raise NotFoundError("run_missing", "Run not found")
        state = RunMemory(self.session).load(run_id)
        return {
            "id": row.id,
            "review_id": row.review_id,
            "status": row.status,
            "step_count": row.step_count,
            "usage": row.usage,
            "error_code": row.error_code,
            "cooldown_until": state.cooldown_until,
            "batch_count": state.batch_count,
            "processed": len(state.processed_chunk_ids),
            "remaining": len(state.remaining_chunk_ids),
            "remaining_chunk_ids": state.remaining_chunk_ids,
            "call_counts": state.call_counts,
            "reference_assessments": state.reference_assessments,
            "max_batches": state.max_batches,
            "max_turns": state.max_turns,
            "activity": get_activity(state, row.status),
        }

    def events(self, run_id: str, after: int) -> dict:
        """Read incremental public trace."""
        if self.repository.get(run_id) is None:
            raise NotFoundError("run_missing", "Run not found")
        return {"items": self.repository.events(run_id, after)}

    def resume(self, run_id: str) -> RunAccepted:
        """Explicitly requeue an interrupted run without erasing its checkpoint."""
        self.session.execute(text("BEGIN IMMEDIATE"))
        row = self.repository.get(run_id)
        if row is None:
            raise NotFoundError("run_missing", "Run not found")
        if row.status != "interrupted" and not (
            row.status == "failed" and row.error_code in {
                "rate_limited", "quota_request_too_large",
            }
        ):
            raise ConflictError("not_resumable", "Run cannot resume")
        row.status = "queued"
        row.error_code = None
        row.finished_at = None
        state = RunMemory(self.session).load(run_id)
        state.status = "running"
        state.error_code = None
        state.cooldown_until = None
        RunMemory(self.session).save(state)
        RunEventRecorder(self.session).append(
            run_id,
            RunEventInput(
                agent="harness",
                action="run_resumed",
                output_summary="Checkpoint requeued",
            ),
        )
        return RunAccepted(run_id=row.id, review_id=row.review_id, status=row.status)

    def cancel(self, run_id: str) -> RunAccepted:
        """Stop future processing without deleting a review or its saved results."""
        self.session.execute(text("BEGIN IMMEDIATE"))
        row = self.repository.get(run_id)
        if row is None:
            raise NotFoundError("run_missing", "Run not found")
        if row.status == "cancelled":
            return RunAccepted(
                run_id=row.id, review_id=row.review_id, status=row.status,
            )
        if row.status not in {"queued", "running", "interrupted", "failed"}:
            raise ConflictError("not_cancellable", "This run has already finished")
        previous_error = row.error_code
        row.status = "cancelled"
        row.error_code = "cancelled_by_user"
        row.finished_at = datetime.now(timezone.utc)
        state = RunMemory(self.session).load(run_id)
        state.status = "cancelled"
        state.error_code = "cancelled_by_user"
        state.cooldown_until = None
        RunMemory(self.session).save(state)
        RunEventRecorder(self.session).append(run_id, RunEventInput(
            agent="harness", action="run_cancelled",
            output_summary="Stopped by user; saved review results retained",
            payload={"previous_error_code": previous_error},
        ))
        return RunAccepted(run_id=row.id, review_id=row.review_id, status=row.status)
