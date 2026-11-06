"""Conservative claim identity and provenance-safe evidence consolidation."""

import unicodedata

from app.harness.output_gate import OutputGate, normalize_quote
from app.harness.state import RunScope


def finding_key(finding: dict) -> tuple:
    """Match content without erasing punctuation, numbers or negation."""
    claim = unicodedata.normalize("NFC", finding["claim"]).casefold()
    return (
        finding["criterion_code"], finding["kind"],
        tuple(sorted(set(finding.get("compared_paper_ids", [])))),
        " ".join(claim.split()),
    )


def merge_evidence(
    existing: dict, incoming: dict, gate: OutputGate, scope: RunScope,
) -> tuple[list[dict], int]:
    """Union valid source references; invalid quotes never poison a match."""
    sources = []
    seen = set()
    added = 0
    for position, finding in enumerate((existing, incoming)):
        for reference in finding["evidence"]:
            # Check provenance independently; two-sided comparison is checked
            # again on the complete union before it can reach the verifier.
            probe = {
                "criterion_code": finding["criterion_code"],
                "claim": finding["claim"], "kind": "analysis",
                "compared_paper_ids": [], "evidence": [reference],
            }
            if not gate.validate(probe, scope).passed:
                continue
            identity = tuple(
                normalize_quote(reference["quote"]) if key == "quote"
                else reference.get(key) for key in (
                    "paper_id", "content_version", "chunk_id", "quote",
                    "locator_type", "locator_value", "span_id",
                    "start_char", "end_char",
                )
            )
            if identity in seen:
                continue
            seen.add(identity)
            sources.append(reference)
            if position == 1:
                added += 1
    return sources, added
