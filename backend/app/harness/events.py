"""Ordered structured trace for the harness inspector."""

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.persistence.orm_models import RunEventRow


class RunEventInput(BaseModel):
    """Public decision metadata; never store raw prompts or secrets."""

    agent: str
    action: str
    tool: str | None = None
    permission_result: str | None = None
    input_summary: str = ""
    output_summary: str = ""
    payload: dict = Field(default_factory=dict)


class RunEventRecorder:
    """Append events within the same transaction as their checkpoint."""

    def __init__(self, session: Session | None = None, on_event=None):
        self.session = session
        self.on_event = on_event
        self.items: list[dict] = []

    def append(self, run_id: str, event: RunEventInput) -> None:
        """Allocate monotonically increasing sequence numbers per run."""
        if self.session is None:
            sequence = 1 + sum(item["run_id"] == run_id for item in self.items)
        else:
            sequence = 1 + (
                self.session.scalar(
                    select(func.max(RunEventRow.sequence)).where(
                        RunEventRow.run_id == run_id
                    )
                )
                or 0
            )
        data = event.model_dump()
        data.update(
            id=str(uuid4()),
            run_id=run_id,
            sequence=sequence,
            timestamp=datetime.now(timezone.utc),
        )
        if self.session is None:
            self.items.append(data)
        else:
            self.session.add(RunEventRow(**data))
            self.session.flush()
        if self.on_event is not None:
            self.on_event(run_id, event)
