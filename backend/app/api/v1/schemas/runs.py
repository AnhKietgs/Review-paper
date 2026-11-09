"""Run lifecycle request and response contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class RunRequest(BaseModel):
    """Full review or verification of edits, always on a new revision."""

    mode: Literal["review", "verify"] = "review"


class RunAccepted(BaseModel):
    """Accepted background execution and its preserved review revision."""

    run_id: str
    review_id: str
    status: str


class ResumeRunRequest(BaseModel):
    """Optional explicit trial extension; absence preserves ordinary resume."""

    model_config = ConfigDict(extra="forbid")
    token_budget: Literal[90000] | None = None
