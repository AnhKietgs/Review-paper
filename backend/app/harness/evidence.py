"""Deterministic source spans and authoritative evidence materialization."""

import re

from pydantic import ValidationError

from app.agents.schemas import EvidenceSelection
from app.harness.state import RunScope

SPAN_MAX_CHARS = 480


def build_spans(text: str) -> list[dict]:
    """Partition all original characters into stable bounded Unicode ranges.

    Positions count Python Unicode code points; end_char is exclusive. Prefer
    sentence/line or whitespace boundaries, never normalize or discard text.
    """
    spans = []
    start = 0
    while start < len(text):
        end = min(start + SPAN_MAX_CHARS, len(text))
        if end < len(text):
            boundaries = list(re.finditer(r"[.!?]\s+|\n\s*\n|\s+", text[start:end]))
            if boundaries and boundaries[-1].end() >= SPAN_MAX_CHARS // 2:
                end = start + boundaries[-1].end()
        spans.append({
            "id": f"s{len(spans)}", "start_char": start, "end_char": end,
            "text": text[start:end],
        })
        start = end
    return spans


def span_source(chunk: dict) -> dict:
    """Present the text once with selection IDs; offsets stay in system memory."""
    return {
        **{key: value for key, value in chunk.items() if key != "text"},
        "spans": [
            {"id": span["id"], "text": span["text"]}
            for span in build_spans(chunk["text"])
        ],
    }


class EvidenceResolutionError(ValueError):
    """Safe source-resolution reason to record without fabricated evidence."""


class EvidenceResolver:
    """Resolve only selections visible to a producer in the frozen run scope."""

    def __init__(self, catalog):
        self.catalog = catalog

    def resolve(self, selections: list[dict], scope: RunScope, sources: list) -> list:
        """Derive quote, identity, positions and locator from original sources."""
        allowed = {source["id"]: source for source in sources}
        resolved = []
        for raw in selections:
            try:
                selection = EvidenceSelection.model_validate(raw)
            except ValidationError as exc:
                raise EvidenceResolutionError("invalid_selection") from exc
            source = allowed.get(selection.chunk_id)
            if source is None:
                raise EvidenceResolutionError("source_not_supplied")
            chunk = self.catalog.chunk(selection.chunk_id)
            if (
                chunk is None
                or not scope.permits(chunk["paper_id"], chunk["content_version"])
                or chunk["paper_id"] != source["paper_id"]
                or chunk["content_version"] != source["content_version"]
                or not self.catalog.is_active(chunk["paper_id"])
            ):
                raise EvidenceResolutionError("source_version_mismatch")
            shown = next((
                span for span in source.get("spans", [])
                if span["id"] == selection.span_id
            ), None)
            if shown is None:
                raise EvidenceResolutionError("span_not_supplied")
            span = next((
                item for item in build_spans(chunk["text"])
                if item["id"] == selection.span_id
            ), None)
            if span is None or span["text"] != shown["text"]:
                raise EvidenceResolutionError("source_content_changed")
            locator = chunk.get("locator")
            if (
                not locator or locator["status"] != "resolved"
                or locator["type"] not in {"pdf_page", "docx_paragraph"}
                or not locator["value"]
            ):
                raise EvidenceResolutionError("unresolved_locator")
            resolved.append({
                "paper_id": chunk["paper_id"],
                "content_version": chunk["content_version"],
                "chunk_id": chunk["id"], "quote": span["text"],
                "locator_type": locator["type"], "locator_value": locator["value"],
                "span_id": span["id"], "start_char": span["start_char"],
                "end_char": span["end_char"],
            })
        return resolved
