"""Environment backed application settings."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class Settings:
    """Configuration shared by API and worker."""

    data_dir: Path
    demo_llm_mode: Literal["fixture", "groq"]
    groq_api_key: str | None
    groq_supervisor_model: str
    groq_scientific_review_model: str
    groq_related_work_model: str
    groq_evidence_verifier_model: str
    groq_rate_limit_wait_seconds: int
    groq_tokens_per_minute: int = 8000
    groq_requests_per_minute: int = 30
    review_token_budget: int = 50000
    review_findings_per_criterion: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        """Load a fresh snapshot without exporting secrets to routes."""
        mode = os.getenv("DEMO_LLM_MODE", "fixture")
        if mode not in {"fixture", "groq"}:
            raise ValueError("DEMO_LLM_MODE must be fixture or groq")
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            demo_llm_mode=mode,
            groq_api_key=os.getenv("GROQ_API_KEY") or None,
            groq_supervisor_model=os.getenv(
                "GROQ_SUPERVISOR_MODEL", "openai/gpt-oss-20b"
            ),
            groq_scientific_review_model=os.getenv(
                "GROQ_SCIENTIFIC_REVIEW_MODEL", "openai/gpt-oss-120b"
            ),
            groq_related_work_model=os.getenv(
                "GROQ_RELATED_WORK_MODEL", "openai/gpt-oss-20b"
            ),
            groq_evidence_verifier_model=os.getenv(
                "GROQ_EVIDENCE_VERIFIER_MODEL", "openai/gpt-oss-20b"
            ),
            groq_rate_limit_wait_seconds=max(
                1, int(os.getenv("GROQ_RATE_LIMIT_WAIT_SECONDS", "60"))
            ),
            groq_tokens_per_minute=max(
                1, int(os.getenv("GROQ_TOKENS_PER_MINUTE", "8000"))
            ),
            groq_requests_per_minute=max(
                1, int(os.getenv("GROQ_REQUESTS_PER_MINUTE", "30"))
            ),
            review_token_budget=max(1, int(os.getenv("REVIEW_TOKEN_BUDGET", "50000"))),
            review_findings_per_criterion=max(
                1, int(os.getenv("REVIEW_FINDINGS_PER_CRITERION", "2")),
            ),
        )
