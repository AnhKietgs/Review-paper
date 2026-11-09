"""Strict structured output contracts for each agent role."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Reject unexpected agent output fields."""

    model_config = ConfigDict(extra="forbid")


class EvidenceReference(StrictModel):
    """Exact source/version/quote needed to check a claim."""

    paper_id: str
    content_version: int
    chunk_id: str
    quote: str = Field(min_length=1)
    locator_type: Literal["pdf_page", "docx_paragraph"]
    locator_value: str
    span_id: str | None = None
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, gt=0)


class FindingContent(StrictModel):
    """Claim fields shared by model selections and canonical findings."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    criterion_code: str
    claim: str = Field(min_length=1)
    kind: Literal[
        "analysis", "strength", "limitation", "comparison", "question", "omission"
    ]
    compared_paper_ids: list[str] = Field(default_factory=list)


class FindingDraft(FindingContent):
    """Canonical finding; resolved evidence and support belong to the harness."""

    evidence: list[EvidenceReference]


class EvidenceSelection(StrictModel):
    """The model selects a displayed span; it cannot write quotes or locators."""

    chunk_id: str = Field(min_length=1, max_length=128)
    span_id: str = Field(min_length=1, max_length=32)


class SelectedFinding(FindingContent):
    """Model-facing claim with only source selections as evidence."""

    evidence: list[EvidenceSelection]


class AgentAction(StrictModel):
    """Supervisor requests exactly one next action."""

    action: Literal[
        "analyze", "compare", "verify", "repair", "next_batch",
        "audit_omission", "finish", "synthesize",
    ]
    reason: str
    reference_paper_id: str | None = None


class ScientificOutput(StrictModel):
    """Analysis from the current batch only."""

    analysis: dict[str, str]
    findings: list[FindingDraft]


class ComparisonOutput(StrictModel):
    """Comparison limited to the supplied selected reference batch."""

    findings: list[FindingDraft]
    assessment: Literal["assessed", "not_assessed"]
    reason: str


class SelectedScientificOutput(StrictModel):
    """Scientific producer contract using system-assigned span selections."""

    analysis: dict[str, str]
    findings: list[SelectedFinding]


class ExtractedNote(StrictModel):
    """Short unverified fact candidate with source selections only."""

    criterion_code: str
    text: str = Field(min_length=1, max_length=160)
    evidence: list[EvidenceSelection] = Field(min_length=1, max_length=2)


class ExtractionOutput(StrictModel):
    """Bounded notes, not a full review per source batch."""

    notes: list[ExtractedNote] = Field(max_length=6)


class SelectedComparisonOutput(StrictModel):
    """Comparator producer contract using system-assigned span selections."""

    findings: list[SelectedFinding]
    assessment: Literal["assessed", "not_assessed"]
    reason: str


class EvidenceAssessment(StrictModel):
    """Semantic support judgment, subject to deterministic provenance gate."""

    finding_id: str
    status: Literal["supported", "unsupported", "uncertain"]
    reason: str


class VerificationOutput(StrictModel):
    """One assessment per pending finding."""

    assessments: list[EvidenceAssessment]
