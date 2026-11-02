"""Optional sign-off and export of immutable AI report snapshots."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError
from app.domain.policies.approval import ApprovalPolicy
from app.harness.memory import RunMemory
from app.harness.output_gate import OutputGate
from app.infrastructure.persistence.orm_models import RunRow
from app.infrastructure.persistence.source_catalog import SqlSourceCatalog
from app.services.report_composer import ReportComposer
from app.services.review_service import ReviewService


class ApprovalService:
    """Serve AI reports and support optional explicit sign-off."""

    def __init__(self, session: Session):
        self.session = session
        self.reviews = ReviewService(session)

    def approve(self, review_id: str, confirmations: list[str]):
        """Keep uncertain claims labeled even after explicit confirmation."""
        review = self.reviews.get(review_id)
        if review.status == "approved":
            return review
        run = self.session.scalar(
            select(RunRow)
            .where(RunRow.review_id == review_id)
            .order_by(RunRow.created_at.desc())
            .limit(1)
        )
        if run is None or run.status != "completed":
            raise ConflictError(
                "review_incomplete",
                "A completed review or verification run is required",
            )
        findings = [item.model_dump() for item in review.findings]
        if not ApprovalPolicy.can_approve(findings, set(confirmations)):
            raise ConflictError(
                "unverified_findings",
                "Verify pending edits and resolve unsupported findings",
            )
        state = RunMemory(self.session).load(run.id)
        gate = OutputGate(SqlSourceCatalog(self.session))
        for finding in findings:
            draft = {
                key: value
                for key, value in finding.items()
                if key not in {"status", "verdict"}
            }
            if not gate.validate(draft, state.scope).passed:
                raise ConflictError(
                    "invalid_evidence", "Source provenance failed final approval gate"
                )
        row = self.reviews.repository.get(review_id)
        row.status = "approved"
        row.reviewer_edits = {**row.reviewer_edits, "confirmations": confirmations}
        report = ReportComposer().render_markdown(self.reviews.get(review_id))
        mode = state.llm_mode
        row.approved_markdown = (
            f"> Chế độ tạo: **{mode}**. "
            + (
                "Fixture minh họa luồng; không phải kết quả AI trực tiếp.\n\n"
                if mode == "fixture"
                else "Bản AI đã được người dùng duyệt.\n\n"
            )
            + report
        )
        self.session.flush()
        return self.reviews.get(review_id)

    def export(self, review_id: str) -> str:
        """Return the frozen AI report when the run completes."""
        review = self.reviews.get(review_id)
        row = self.reviews.repository.get(review_id)
        if review.status not in {"completed", "approved"} or not row.approved_markdown:
            raise ConflictError(
                "review_incomplete", "Complete the AI review before export"
            )
        return row.approved_markdown
