"""Review draft CRUD and revision preservation."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.v1.schemas.reviews import (
    FindingInput,
    FindingRead,
    ReviewCreate,
    ReviewRead,
    ReviewReferenceRead,
    ReviewUpdate,
)
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.infrastructure.persistence.orm_models import (
    FindingRow,
    ReviewReferenceRow,
    ReviewRow,
    RunRow,
)
from app.infrastructure.persistence.paper_repository import SqlPaperRepository
from app.infrastructure.persistence.review_repository import SqlReviewRepository
from app.infrastructure.persistence.rubric_repository import SqlRubricRepository
from app.infrastructure.persistence.run_repository import SqlRunRepository


class ReviewService:
    """Manage review revisions and selected document scope."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = SqlReviewRepository(session)
        self.papers = SqlPaperRepository(session)
        self.rubrics = SqlRubricRepository(session)

    def _required(self, review_id: str) -> ReviewRow:
        row = self.repository.get(review_id)
        if row is None:
            raise NotFoundError("review_missing", "Review not found")
        return row

    def _read(self, row: ReviewRow) -> ReviewRead:
        criterion_order = {
            item.code: item.order_index
            for item in self.rubrics.criteria(row.rubric_id, row.rubric_version)
        }
        findings = sorted(
            self.repository.findings(row.id),
            key=lambda item: criterion_order.get(
                item.criterion_code, len(criterion_order)
            ),
        )
        return ReviewRead(
            id=row.id,
            paper_id=row.paper_id,
            paper_content_version=row.paper_content_version,
            rubric_id=row.rubric_id,
            rubric_version=row.rubric_version,
            revision=row.revision,
            parent_revision_id=row.parent_revision_id,
            status=row.status,
            analysis=row.analysis,
            summary=row.summary,
            reviewer_edits=row.reviewer_edits,
            references=[
                ReviewReferenceRead(
                    paper_id=item.paper_id,
                    paper_content_version=item.paper_content_version,
                )
                for item in self.repository.references(row.id)
            ],
            findings=[
                FindingRead(
                    id=item.id,
                    criterion_code=item.criterion_code,
                    kind=item.kind,
                    compared_paper_ids=item.compared_paper_ids,
                    claim=item.claim,
                    evidence=item.evidence,
                    status=item.status,
                    verdict=item.verdict,
                )
                for item in findings
            ],
        )

    def create(self, data: ReviewCreate) -> ReviewRead:
        """Freeze the chosen paper/rubric versions for this draft."""
        main = self.papers.get(data.paper_id)
        rubric = self.rubrics.get(data.rubric_id)
        if main is None:
            raise NotFoundError("paper_missing", "Main paper not found")
        if rubric is None:
            raise NotFoundError("rubric_missing", "Rubric not found")
        reference_ids = data.reference_paper_ids
        if data.paper_id in reference_ids or len(reference_ids) != len(
            set(reference_ids)
        ):
            raise ValidationError(
                "invalid_reference", "References must be distinct from main"
            )
        references = []
        for paper_id in reference_ids:
            paper = self.papers.get(paper_id)
            if paper is None:
                raise NotFoundError("paper_missing", "Reference paper not found")
            references.append(paper)
        row = ReviewRow(
            id=str(uuid4()),
            paper_id=main.id,
            paper_content_version=main.content_version,
            rubric_id=rubric.id,
            rubric_version=rubric.version,
            revision=1,
            parent_revision_id=None,
            status="draft",
            analysis={},
            summary="",
            reviewer_edits={},
        )
        self.session.add(row)
        self.session.flush()
        for reference in references:
            self.session.add(
                ReviewReferenceRow(
                    id=str(uuid4()),
                    review_id=row.id,
                    paper_id=reference.id,
                    paper_content_version=reference.content_version,
                )
            )
        self.session.flush()
        return self._read(row)

    def get(self, review_id: str) -> ReviewRead:
        """Read one active revision."""
        return self._read(self._required(review_id))

    def list(self, limit: int, offset: int) -> dict:
        """Paginate active revisions."""
        rows, total = self.repository.list(limit, offset)
        latest_run_ids = SqlRunRepository(self.session).latest_ids_for_reviews(
            [row.id for row in rows]
        )
        return {
            "items": [
                self._read(row).model_copy(
                    update={"latest_run_id": latest_run_ids.get(row.id)}
                )
                for row in rows
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def _replace_findings(self, row: ReviewRow, findings: list[FindingInput]) -> None:
        existing = {item.id: item for item in self.repository.findings(row.id)}
        seen = set()
        for item in findings:
            if item.id and (item.id not in existing or item.id in seen):
                raise ValidationError(
                    "invalid_finding_id", "Finding must belong to this review"
                )
            finding_id = item.id or str(uuid4())
            seen.add(finding_id)
            values = item.model_dump(exclude={"id", "status"})
            current = existing.get(finding_id)
            if current is None:
                self.session.add(
                    FindingRow(
                        id=finding_id,
                        review_id=row.id,
                        **values,
                        status="pending",
                        verdict="",
                    )
                )
            elif any(getattr(current, key) != value for key, value in values.items()):
                for key, value in values.items():
                    setattr(current, key, value)
                current.status = "pending"
                current.verdict = "Edited; evidence verification required"
        for finding_id, current in existing.items():
            if finding_id not in seen:
                self.session.delete(current)

    def _ensure_idle(self, review_id: str) -> None:
        active = self.session.scalar(
            select(RunRow).where(
                RunRow.review_id == review_id,
                RunRow.status.in_(["queued", "running", "interrupted"]),
            )
        )
        if active:
            raise ConflictError(
                "run_active", "Wait for the run to finish before editing"
            )

    def update(self, review_id: str, data: ReviewUpdate) -> ReviewRead:
        """Edit a draft and reset edited finding support state."""
        row = self._required(review_id)
        if row.status != "draft":
            raise ConflictError(
                "review_locked", "Create a new revision to edit a completed review"
            )
        self._ensure_idle(review_id)
        if data.summary is not None:
            row.summary = data.summary
            row.reviewer_edits = {**row.reviewer_edits, "summary": data.summary}
        if data.analysis is not None:
            row.analysis = data.analysis
        if data.reviewer_edits is not None:
            row.reviewer_edits = data.reviewer_edits
        if data.findings is not None:
            self._replace_findings(row, data.findings)
        self.session.flush()
        return self._read(row)

    def new_revision(self, review_id: str, lock: bool = True) -> ReviewRead:
        """Copy selected versions and findings into a new draft ID."""
        if lock:
            self.session.execute(text("BEGIN IMMEDIATE"))
        source = self._required(review_id)
        revisions = list(self.session.scalars(select(ReviewRow)))
        by_id = {item.id: item for item in revisions}

        def root_id(item: ReviewRow) -> str:
            """Resolve the root of a revision chain."""
            seen = set()
            while item.parent_revision_id in by_id and item.id not in seen:
                seen.add(item.id)
                item = by_id[item.parent_revision_id]
            return item.id

        root = root_id(source)
        next_number = (
            max(item.revision for item in revisions if root_id(item) == root) + 1
        )
        row = ReviewRow(
            id=str(uuid4()),
            paper_id=source.paper_id,
            paper_content_version=source.paper_content_version,
            rubric_id=source.rubric_id,
            rubric_version=source.rubric_version,
            revision=next_number,
            parent_revision_id=source.id,
            status="draft",
            analysis=dict(source.analysis),
            summary=source.summary,
            reviewer_edits=dict(source.reviewer_edits),
        )
        self.session.add(row)
        self.session.flush()
        for reference in self.repository.references(source.id):
            self.session.add(
                ReviewReferenceRow(
                    id=str(uuid4()),
                    review_id=row.id,
                    paper_id=reference.paper_id,
                    paper_content_version=reference.paper_content_version,
                )
            )
        for finding in self.repository.findings(source.id):
            self.session.add(
                FindingRow(
                    id=str(uuid4()),
                    review_id=row.id,
                    criterion_code=finding.criterion_code,
                    claim=finding.claim,
                    kind=finding.kind,
                    compared_paper_ids=list(finding.compared_paper_ids),
                    evidence=list(finding.evidence),
                    status=finding.status,
                    verdict=finding.verdict,
                )
            )
        self.session.flush()
        return self._read(row)

    def delete(self, review_id: str) -> None:
        """Soft delete one revision and cancel unfinished work for it."""
        self.session.execute(text("BEGIN IMMEDIATE"))
        row = self._required(review_id)
        deleted_at = datetime.now(timezone.utc)
        active_runs = self.session.scalars(
            select(RunRow).where(
                RunRow.review_id == review_id,
                RunRow.status.in_(["queued", "running", "interrupted"]),
            )
        )
        for run in active_runs:
            run.status = "cancelled"
            run.error_code = "cancelled_by_user"
            run.finished_at = deleted_at
        row.deleted_at = deleted_at
