"""Review draft and finding transfer schemas."""

from pydantic import BaseModel, Field


class ReviewCreate(BaseModel):
    """Selection of main paper, rubric and manual related papers."""

    paper_id: str
    rubric_id: str
    reference_paper_ids: list[str] = Field(default_factory=list)


class FindingInput(BaseModel):
    """Human editable draft finding."""

    id: str | None = None
    criterion_code: str = "general"
    kind: str = "analysis"
    compared_paper_ids: list[str] = Field(default_factory=list)
    claim: str = Field(min_length=1)
    evidence: list[dict] = Field(default_factory=list)
    status: str = "pending"


class FindingRead(FindingInput):
    """Stored finding with verifier verdict."""

    id: str
    verdict: str = ""


class ReviewUpdate(BaseModel):
    """Editable draft fields only."""

    summary: str | None = None
    analysis: dict | None = None
    reviewer_edits: dict | None = None
    findings: list[FindingInput] | None = None


class ReviewReferenceRead(BaseModel):
    """Frozen source reference."""

    paper_id: str
    paper_content_version: int


class ReviewRead(BaseModel):
    """One review revision."""

    id: str
    paper_id: str
    paper_content_version: int
    rubric_id: str
    rubric_version: int
    revision: int
    parent_revision_id: str | None
    status: str
    analysis: dict
    summary: str
    reviewer_edits: dict
    references: list[ReviewReferenceRead]
    findings: list[FindingRead]
    latest_run_id: str | None = None


class ReviewPage(BaseModel):
    """Paginated review revisions."""

    items: list[ReviewRead]
    total: int
    limit: int
    offset: int
