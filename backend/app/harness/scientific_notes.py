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
    """Merge identical facts and retain up to two independent source spans."""
    result, positions = [], {}
    for note in existing + incoming:
        key = (note["criterion_code"], " ".join(note["text"].split()).casefold())
        index = positions.get(key)
        if index is None:
            positions[key] = len(result)
            result.append({**note, "evidence": list(note["evidence"])})
            continue
        merged = result[index]
        identities = {
            (item["chunk_id"], item["span_id"]) for item in merged["evidence"]
        }
        for reference in note["evidence"]:
            identity = (reference["chunk_id"], reference["span_id"])
            if identity not in identities and len(merged["evidence"]) < 2:
                merged["evidence"].append(reference)
                identities.add(identity)
    return result
