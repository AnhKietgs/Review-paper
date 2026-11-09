"""Run lifecycle request and response contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.harness.token_budget import MAX_REVIEW_TOKEN_BUDGET


class RunRequest(BaseModel):
    """Full review or verification of edits, always on a new revision."""

    mode: Literal["review", "verify"] = "review"


class RunAccepted(BaseModel):
    """Accepted background execution and its preserved review revision."""

    run_id: str
    review_id: str
    status: str


class ResumeRunRequest(BaseModel):
    """Optional explicit budget extension; absence preserves ordinary resume."""

    model_config = ConfigDict(extra="forbid")
    token_budget: int | None = Field(
        default=None, ge=1, le=MAX_REVIEW_TOKEN_BUDGET,
    )
