"""PDF conversion keeps independent source page evidence."""

from pathlib import Path
from uuid import uuid4

import pymupdf
import pytest

from app.ingestion.document_ingress import DocumentIngress, IngestionError


def make_pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    document.save(path)


def test_pdf_page_two_is_original_source(tmp_path: Path):
    source = tmp_path / "paper.pdf"
    make_pdf(source, ["Introduction and methods.", "Distinct result on page two."])
    result = DocumentIngress().ingest(source, uuid4(), 1)
    assert "Distinct result" in result.markdown
    chunk = next(
        chunk for chunk in result.chunks if "Distinct result" in chunk.markdown_text
    )
    locator = next(item for item in result.locators if item.chunk_id == chunk.id)
    assert locator.locator_type == "pdf_page"
    assert locator.locator_value == "2"
    assert locator.status == "resolved"


def test_scanned_pdf_is_rejected(tmp_path: Path):
    source = tmp_path / "scanned.pdf"
    make_pdf(source, [""])
    with pytest.raises(IngestionError, match="text layer"):
        DocumentIngress().ingest(source, uuid4(), 1)


def test_duplicate_text_keeps_distinct_original_page_locations(tmp_path: Path):
    source = tmp_path / "ambiguous.pdf"
    make_pdf(source, ["Identical finding.", "Identical finding."])
    result = DocumentIngress().ingest(source, uuid4(), 1)
    assert [locator.locator_value for locator in result.locators] == ["1", "2"]
    assert all(locator.status == "resolved" for locator in result.locators)


def test_page_locator_survives_markdown_formatting_changes(tmp_path: Path):
    source = tmp_path / "formatted.pdf"
    make_pdf(source, ["A finding split across extracted lines."])

    class ReformattedConverter:
        def convert(self, _path):
            return "# A finding: split across extracted lines."

    result = DocumentIngress(converter=ReformattedConverter()).ingest(
        source, uuid4(), 1
    )
    assert result.chunks[0].markdown_text == "A finding split across extracted lines."
    assert result.chunks[0].markdown_start == result.chunks[0].markdown_end == 0
    assert result.locators[0].locator_value == "1"
    assert result.locators[0].status == "resolved"
