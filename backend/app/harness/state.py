"""Serializable harness state and document permission scope."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.agents.schemas import AgentAction


class RunScope(BaseModel):
    """Frozen documents and rubric an execution may access."""

    main_paper_id: str
    main_version: int
    reference_versions: dict[str, int] = Field(default_factory=dict)
    rubric_id: str
    rubric_version: int

    def permits(self, paper_id: str, version: int) -> bool:
        """Check a source version against the exact review snapshot."""
        if paper_id == self.main_paper_id:
            return version == self.main_version
        return self.reference_versions.get(paper_id) == version


class TurnProgress(BaseModel):
    """Reusable completed steps of one unfinished logical turn."""

    action: AgentAction
    context_role: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    context: dict | None = None
    output: dict | None = None
    work_contexts: list[dict] = Field(default_factory=list)
    work_outputs: list[dict] = Field(default_factory=list)


class RunState(BaseModel):
    """Durable progress; no credentials or hidden reasoning."""

    run_id: str
    review_id: str
    scope: RunScope
    remaining_chunk_ids: list[str] = Field(default_factory=list)
    processed_chunk_ids: list[str] = Field(default_factory=list)
    current_batch_ids: list[str] = Field(default_factory=list)
    pending_findings: list[dict] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    repair_queue: list[dict] = Field(default_factory=list)
    repair_attempted_ids: list[str] = Field(default_factory=list)
    omission_audits: list[dict] = Field(default_factory=list)
    repair_count: int = 0
    max_repairs: int = 8
    analysis: dict[str, list[str]] = Field(default_factory=dict)
    reference_assessments: dict[str, dict] = Field(default_factory=dict)
    comparison_progress: dict[str, dict] = Field(default_factory=dict)
    batch_count: int = 0
    turn_count: int = 0
    max_batches: int = 20
    max_turns: int = 120
    token_budget: int = Field(default=50000, ge=1)
    token_spent: int = Field(default=0, ge=0)
    max_findings_per_criterion: int = Field(default=4, ge=1)
    status: str = "running"
    call_counts: dict[str, int] = Field(default_factory=dict)
    initialized: bool = False
    turn_progress: TurnProgress | None = None
    error_code: str | None = None
    cooldown_until: datetime | None = None
    llm_mode: str = "fixture"
    efficient_review: bool = False
    two_phase_review: bool = False
    read_notes: list[dict] = Field(default_factory=list)
    scientific_synthesized: bool = False
    max_omission_topics: int | None = None
