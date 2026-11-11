"""Run and trace SQL adapter."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.persistence.orm_models import RunEventRow, RunRow


class SqlRunRepository:
    """Read run status and ordered event pages."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, run_id: str) -> RunRow | None:
        """Read a durable execution."""
        return self.session.get(RunRow, run_id)

    def latest_ids_for_reviews(self, review_ids: list[str]) -> dict[str, str]:
        """Read the latest run for each exact revision in one page query."""
        if not review_ids:
            return {}
        rows = self.session.execute(
            select(RunRow.review_id, RunRow.id)
            .where(RunRow.review_id.in_(review_ids))
            .order_by(RunRow.created_at.desc(), RunRow.id.desc())
        )
        latest: dict[str, str] = {}
        for review_id, run_id in rows:
            latest.setdefault(review_id, run_id)
        return latest

    def events(self, run_id: str, after: int) -> list[dict]:
        """Return up to 1000 new trace records."""
        rows = self.session.scalars(
            select(RunEventRow)
            .where(
                RunEventRow.run_id == run_id,
                RunEventRow.sequence > after,
            )
            .order_by(RunEventRow.sequence)
            .limit(1000)
        )
        return [
            {
                column.name: getattr(row, column.name)
                for column in RunEventRow.__table__.columns
            }
            for row in rows
        ]
