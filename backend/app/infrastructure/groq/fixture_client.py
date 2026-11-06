"""Deterministic demo responses that still traverse every harness gate."""

import json
from uuid import uuid4

from app.agents.schemas import (
    AgentAction,
    ComparisonOutput,
    ScientificOutput,
    VerificationOutput,
)


def _evidence(chunk: dict) -> dict:
    locator = chunk["locator"] or {"type": "pdf_page", "value": "unknown"}
    return {
        "paper_id": chunk["paper_id"],
        "content_version": chunk["content_version"],
        "chunk_id": chunk["id"],
        "quote": " ".join(chunk["text"].split())[:180],
        "locator_type": locator["type"],
        "locator_value": locator["value"],
    }


class FixtureClient:
    """Transparent fixture mode; quoted observations are not live AI reviews."""

    def __init__(self, force_action: str | None = None, bad_source: bool = False):
        self.force_action = force_action
        self.bad_source = bad_source
        self.usage = {"calls": 0, "tokens": 0}

    def generate_json(self, messages, schema):
        """Return structured sample output using actual context source IDs."""
        self.usage["calls"] += 1
        context = json.loads(messages[-1]["content"])
        if schema is AgentAction:
            action = self.force_action or context["allowed_actions"][0]
            refs = context["unassessed_references"]
            return schema(
                action=action,
                reason="Fixture scheduling rule",
                reference_paper_id=refs[0] if refs and action == "compare" else None,
            )
        if schema is ScientificOutput:
            chunks = context["chunks"]
            findings = []
            for chunk in chunks:
                source = _evidence(chunk)
                if self.bad_source:
                    source["chunk_id"] = "outside-run"
                findings.append(
                    {
                        "id": str(uuid4()),
                        "criterion_code": context["criteria"][0]["code"],
                        "claim": f"Trích đoạn tài liệu ghi: {source['quote']}",
                        "kind": "analysis",
                        "evidence": [source],
                        "compared_paper_ids": [],
                    }
                )
            return schema(
                analysis={
                    key: "Fixture: xem các nhận xét có trích dẫn bên dưới."
                    for key in (
                        "objective",
                        "methodology",
                        "results",
                        "contributions",
                        "strengths",
                        "limitations",
                        "questions",
                    )
                },
                findings=findings,
            )
        if schema is ComparisonOutput:
            main_id = context["scope"]["main_paper_id"]
            main = next(
                item for item in context["chunks"] if item["paper_id"] == main_id
            )
            related = next(
                item for item in context["chunks"] if item["paper_id"] != main_id
            )
            left, right = _evidence(main), _evidence(related)
            remaining = context.get("finding_policy", {}).get("remaining", {})
            criterion = next((
                item["code"] for item in context["criteria"]
                if remaining.get(item["code"], 1) > 0
            ), context["criteria"][0]["code"])
            return schema(
                assessment="assessed",
                reason="Fixture: đối chiếu hai trích đoạn.",
                findings=[
                    {
                        "id": str(uuid4()),
                        "criterion_code": criterion,
                        "claim": (
                            f"Paper chính ghi ‘{left['quote']}’; "
                            f"nguồn đối chiếu ghi ‘{right['quote']}’."
                        ),
                        "kind": "comparison",
                        "evidence": [left, right],
                        "compared_paper_ids": [related["paper_id"]],
                    }
                ],
            )
        if schema is VerificationOutput:
            return schema(
                assessments=[
                    {
                        "finding_id": finding["id"],
                        "status": "supported",
                        "reason": (
                            "Fixture: hỗ trợ mô phỏng; "
                            "provenance vẫn qua gate, không đánh giá ngữ nghĩa."
                        ),
                    }
                    for finding in context["pending_findings"]
                ]
            )
        raise ValueError("Unknown fixture schema")
