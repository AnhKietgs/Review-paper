"""Safely reconcile legacy locators against the unchanged original file."""

import argparse
import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.persistence.orm_models import (
    ChunkRow,
    LocatorRow,
    PaperVersionRow,
)
from app.infrastructure.persistence.unit_of_work import UnitOfWork
from app.ingestion.docx_locator import extract_docx_paragraphs
from app.ingestion.pdf_locator import extract_pdf_pages


def reconcile_locators(session: Session, paper_id: str, version: int) -> dict:
    """Resolve only locators whose chunk matches the same original page exactly."""
    source = session.get(PaperVersionRow, (paper_id, version))
    if source is None:
        raise ValueError("Source version not found")
    path = Path(source.file_path)
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if file_hash != source.source_file_hash:
        raise ValueError("Original source file hash does not match the saved version")
    if source.media_type == "application/pdf":
        sections = extract_pdf_pages(path)
    elif path.suffix.lower() == ".docx":
        sections = extract_docx_paragraphs(path)
    else:
        raise ValueError("Unsupported source format")
    original_text = {
        (locator_type, locator_value): text
        for locator_value, text, locator_type in sections
    }
    chunks = session.scalars(
        select(ChunkRow).where(
            ChunkRow.paper_id == paper_id,
            ChunkRow.content_version == version,
        )
    )
    checked = repaired = 0
    for chunk in chunks:
        locator = session.scalar(
            select(LocatorRow).where(LocatorRow.chunk_id == chunk.id)
        )
        if locator is None or locator.status != "unresolved_locator":
            continue
        checked += 1
        text = original_text.get((locator.locator_type, locator.locator_value))
        source_matches = bool(
            text
            and chunk.markdown_text == text
            and chunk.text_hash == hashlib.sha256(text.encode("utf-8")).hexdigest()
            and locator.quote == text[:300]
        )
        version_matches = (
            chunk.markdown_start == chunk.markdown_end == 0
            and locator.source_file_hash == file_hash
        )
        if source_matches and version_matches:
            locator.status = "resolved"
            repaired += 1
    session.flush()
    return {"checked": checked, "repaired": repaired, "skipped": checked - repaired}


def main() -> None:
    """Repair a specified version after the updated ingestion code is deployed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper_id")
    parser.add_argument("version", type=int)
    args = parser.parse_args()
    with UnitOfWork() as unit:
        result = reconcile_locators(unit.session, args.paper_id, args.version)
    print(result)


if __name__ == "__main__":
    main()
