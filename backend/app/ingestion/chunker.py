"""Map independent source segments onto Markdown spans."""

import hashlib
import re
from uuid import UUID, uuid4

from app.domain.models.paper import PaperChunk
from app.domain.models.source import SourceLocator


def _whitespace_pattern(text: str) -> str:
    return r"\s+".join(re.escape(part) for part in text.split())


def locate_span(markdown: str, text: str) -> tuple[int, int] | None:
    """Resolve a unique source quote in the normalized document."""
    if not text.strip():
        return None
    matches = list(
        re.finditer(_whitespace_pattern(text), markdown, flags=re.IGNORECASE)
    )
    if len(matches) != 1:
        return None
    return matches[0].span()


def chunk_source(
    markdown: str,
    source_sections: list[tuple[str, str, str]],
    paper_id: UUID,
    content_version: int,
    source_file_hash: str,
) -> tuple[list[PaperChunk], list[SourceLocator]]:
    """Create chunks tied to original pages or paragraphs.

    Markdown alignment is optional: the original extractor already provides
    the page or paragraph number and the exact source text for each chunk.
    """
    chunks: list[PaperChunk] = []
    locators: list[SourceLocator] = []
    for locator_value, text, locator_type in source_sections:
        if not text:
            continue
        span = locate_span(markdown, text)
        start, end = span if span is not None else (0, 0)
        chunk_id = uuid4()
        chunks.append(
            PaperChunk(
                id=chunk_id,
                paper_id=paper_id,
                content_version=content_version,
                order_index=len(chunks),
                markdown_text=markdown[start:end] if span else text,
                text_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                markdown_start=start,
                markdown_end=end,
            )
        )
        locators.append(
            SourceLocator(
                id=uuid4(),
                chunk_id=chunk_id,
                locator_type=locator_type,
                locator_value=locator_value,
                quote=text[:300],
                source_file_hash=source_file_hash,
                status=(
                    "resolved"
                    if locator_type in {"pdf_page", "docx_paragraph"}
                    and locator_value
                    else "unresolved_locator"
                ),
            )
        )
    return chunks, locators
