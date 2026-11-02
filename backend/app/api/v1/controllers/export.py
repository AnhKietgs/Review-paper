"""Approval and Markdown download HTTP boundary."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.api.v1.schemas.reviews import ReviewRead
from app.infrastructure.persistence.unit_of_work import UnitOfWork, get_uow
from app.services.approval_service import ApprovalService

router = APIRouter(prefix="/api/v1/reviews", tags=["approval and export"])


class ApprovalRequest(BaseModel):
    """Explicit confirmations for uncertain verifier judgments."""

    confirmations: list[str] = Field(default_factory=list)


@router.post("/{review_id}/approve", response_model=ReviewRead)
def approve_review(
    review_id: str, data: ApprovalRequest, unit: UnitOfWork = Depends(get_uow)
):
    """Approve eligible findings and freeze the Markdown snapshot."""
    return ApprovalService(unit.session).approve(review_id, data.confirmations)


@router.get("/{review_id}/export.md")
def export_review(review_id: str, unit: UnitOfWork = Depends(get_uow)):
    """Download the exact AI-completed report."""
    report = ApprovalService(unit.session).export(review_id)
    return Response(
        report,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="review-{review_id}.md"'
        },
    )
