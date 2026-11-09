"""Resolve compact reading notes without treating their assertions as verified."""

from uuid import uuid4

from app.harness.evidence import EvidenceResolutionError


def resolve_notes(output, sources, resolver, scope, criteria):
    """Only source-grounded, rubric-bound notes can reach synthesis."""
    valid = []
    for note in output["notes"]:
        if note["criterion_code"] not in criteria:
            continue
        try:
            evidence = resolver.resolve(note["evidence"], scope, sources)
        except EvidenceResolutionError:
            continue
        if not evidence or any(r["paper_id"] != scope.main_paper_id for r in evidence):
            continue
        valid.append({**note, "id": str(uuid4()), "evidence": evidence})
    return {"notes": valid}, len(output["notes"]) - len(valid)


def merge_notes(existing, incoming):
    """Keep distinct source locations; exact repeats do not add model work."""
    result, seen = [], set()
    for note in existing + incoming:
        key = (note["criterion_code"], " ".join(note["text"].split()).casefold(), tuple(
            sorted((r["chunk_id"], r["span_id"]) for r in note["evidence"])
        ))
        if key not in seen:
            result.append(note)
            seen.add(key)
    return result
