"""Legacy locator repair accepts only exact original-source matches."""

from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.infrastructure.persistence.orm_models import (
    Base,
    ChunkRow,
    LocatorRow,
    PaperRow,
    PaperVersionRow,
)
from app.ingestion.document_ingress import DocumentIngress
from app.services.source_locator_service import reconcile_locators


class ReformattedConverter:
    """Force Markdown alignment to fail while PDF page extraction succeeds."""

    def convert(self, _path):
        return "# Reformatted content"


def test_repair_only_exact_original_page_text(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    document = pymupdf.open()
    for text in ("Page one evidence.", "Page two evidence."):
        document.new_page().insert_text((72, 72), text)
    document.save(source)
    paper_id = uuid4()
    ingested = DocumentIngress(ReformattedConverter()).ingest(source, paper_id, 1)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(PaperRow(
            id=str(paper_id), title="Paper", authors=[], year=None, doi=None,
            original_filename="paper.pdf", media_type="application/pdf",
            file_path=str(source), markdown_path="", content_version=1,
            conversion_status="ready",
        ))
        session.add(PaperVersionRow(
            paper_id=str(paper_id), version=1, file_path=str(source),
            markdown_path="", original_filename="paper.pdf",
            media_type="application/pdf",
            source_file_hash=ingested.source_file_hash,
        ))
        for index, (chunk, locator) in enumerate(
            zip(ingested.chunks, ingested.locators)
        ):
            session.add(ChunkRow(
                id=str(chunk.id), paper_id=str(paper_id), content_version=1,
                order_index=index,
                markdown_text=(
                    chunk.markdown_text if index == 0 else "Tampered text"
                ),
                text_hash=chunk.text_hash, markdown_start=chunk.markdown_start,
                markdown_end=chunk.markdown_end,
            ))
            session.add(LocatorRow(
                id=str(locator.id), chunk_id=str(chunk.id),
                locator_type=locator.locator_type,
                locator_value=locator.locator_value, quote=locator.quote,
                source_file_hash=locator.source_file_hash,
                status="unresolved_locator",
            ))
        session.commit()
        result = reconcile_locators(session, str(paper_id), 1)
        assert result == {"checked": 2, "repaired": 1, "skipped": 1}
        first = session.get(LocatorRow, str(ingested.locators[0].id))
        assert first.status == "resolved"
        assert (
            session.get(LocatorRow, str(ingested.locators[1].id)).status
            == "unresolved_locator"
        )
        session.get(PaperVersionRow, (str(paper_id), 1)).source_file_hash = "wrong"
        with pytest.raises(ValueError, match="hash does not match"):
            reconcile_locators(session, str(paper_id), 1)
