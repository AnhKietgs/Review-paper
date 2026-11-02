"""Serializable harness state and document permission scope."""

from pydantic import BaseModel, Field


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
    repair_count: int = 0
    max_repairs: int = 8
    analysis: dict[str, list[str]] = Field(default_factory=dict)
    reference_assessments: dict[str, dict] = Field(default_factory=dict)
    batch_count: int = 0
    turn_count: int = 0
    max_batches: int = 20
    max_turns: int = 80
    status: str = "running"
    call_counts: dict[str, int] = Field(default_factory=dict)
    initialized: bool = False
    error_code: str | None = None
    llm_mode: str = "fixture"
