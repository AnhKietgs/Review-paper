"""Load the shared paper library and ordered rubrics without overwriting edits."""

import argparse
import json
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.schemas.papers import PaperCreate
from app.api.v1.schemas.rubrics import RubricCreate
from app.infrastructure.persistence.orm_models import PaperRow, RubricRow
from app.infrastructure.persistence.unit_of_work import UnitOfWork
from app.services.paper_service import PaperService
from app.services.rubric_service import RubricService


def seed(session: Session, assets: Path) -> dict:
    """Create missing shared records, preserving existing local edits."""
    library = json.loads((assets / "library.json").read_text(encoding="utf-8-sig"))
    papers = {}
    for item in library["papers"]:
        metadata = PaperCreate.model_validate(item)
        source_path = (assets / item["filename"]).resolve()
        if not source_path.is_relative_to(assets.resolve()):
            raise ValueError("Shared source must be inside the library directory")
        existing = session.scalar(
            select(PaperRow).where(
                PaperRow.title == metadata.title, PaperRow.deleted_at.is_(None)
            )
        )
        if existing is None:
            with source_path.open("rb") as source:
                existing = PaperService(session).create(
                    UploadFile(filename=item["filename"], file=source), metadata
                )
        papers[item["key"]] = existing.id
    rubrics = {}
    for item in library["rubrics"]:
        metadata = RubricCreate.model_validate(item)
        existing = session.scalar(
            select(RubricRow).where(
                RubricRow.name == metadata.name, RubricRow.deleted_at.is_(None)
            )
        )
        if existing is None:
            existing = RubricService(session).create(metadata)
        rubrics[item["key"]] = existing.id
    selection = library["review"]
    return {
        "paper_id": papers[selection["paper_key"]],
        "rubric_id": rubrics[selection["rubric_key"]],
        "reference_paper_ids": [papers[key] for key in selection["reference_keys"]],
    }


def main() -> None:
    """Load the shared library explicitly or once on a fresh Docker database."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--if-empty", action="store_true")
    args = parser.parse_args()
    mounted = Path("/app/demo_data")
    assets = (
        mounted
        if mounted.exists()
        else Path(__file__).resolve().parents[3] / "demo_data"
    )
    with UnitOfWork() as unit:
        if args.if_empty and (
            unit.session.scalar(select(PaperRow.id).limit(1))
            or unit.session.scalar(select(RubricRow.id).limit(1))
        ):
            print("Existing library preserved; automatic import skipped.")
            return
        result = seed(unit.session, assets)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
