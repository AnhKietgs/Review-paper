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


class FindingDraft(StrictModel):
    """A proposed claim; support status is owned by the harness."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    criterion_code: str
    claim: str = Field(min_length=1)
    kind: Literal[
        "analysis", "strength", "limitation", "comparison", "question", "omission"
    ]
    evidence: list[EvidenceReference]
    compared_paper_ids: list[str] = Field(default_factory=list)


class AgentAction(StrictModel):
    """Supervisor requests exactly one next action."""

    action: Literal[
        "analyze", "compare", "verify", "repair", "next_batch",
        "audit_omission", "finish",
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


class EvidenceAssessment(StrictModel):
    """Semantic support judgment, subject to deterministic provenance gate."""

    finding_id: str
    status: Literal["supported", "unsupported", "uncertain"]
    reason: str


class VerificationOutput(StrictModel):
    """One assessment per pending finding."""

    assessments: list[EvidenceAssessment]
