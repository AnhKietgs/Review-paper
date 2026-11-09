"""Model-only projections; canonical evidence and source positions stay unchanged."""

from app.harness.evidence import span_source


def source_frames(chunks):
    """Preserve every supplied span identity/text with minimal source metadata."""
    result = []
    for chunk in chunks:
        source = chunk if "spans" in chunk else span_source(chunk)
        result.append({
            **{key: source[key] for key in ("id", "paper_id", "content_version")},
            "spans": [{"id": s["id"], "text": s["text"]} for s in source["spans"]],
        })
    return result


def scientific_context(context):
    """Reading emits small notes; synthesis sees notes AND original evidence."""
    result = {
        "scientific_phase": context["scientific_phase"],
        "chunks": source_frames(context["chunks"]),
        "criteria": context["criteria"],
    }
    if context["scientific_phase"] == "extract":
        result["criteria"] = [
            {key: item[key] for key in ("code", "question")}
            for item in context["criteria"]
        ]
    else:
        result["finding_policy"] = context.get("finding_policy", {})
        result["notes"] = [{
            **{key: n[key] for key in ("id", "criterion_code", "text")},
            "evidence": [{"chunk_id": r["chunk_id"], "span_id": r["span_id"]}
                         for r in n["evidence"]],
        } for n in context["notes"]]
    return result


def verifier_context(context: dict) -> dict:
    """Send source text once and link claims to stable span identities."""
    findings = []
    for finding in context["pending_findings"]:
        references = []
        for reference in finding.get("evidence", []):
            selected = {"chunk_id": reference["chunk_id"]}
            if reference.get("span_id"):
                selected["span_id"] = reference["span_id"]
            else:
                # Legacy evidence can cross span boundaries. Keep its exact quote.
                selected["quote"] = reference["quote"]
            references.append(selected)
        findings.append({
            **{key: finding[key] for key in (
                "id", "claim", "kind", "compared_paper_ids",
            ) if key in finding},
            "evidence": references,
        })
    return {
        "pending_findings": findings, "chunks": source_frames(context["chunks"]),
        "omission_audit": bool(context.get("omission_audit")),
    }
