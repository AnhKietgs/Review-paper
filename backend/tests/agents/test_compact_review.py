"""Economical model transport retains evidence while removing repeated scaffolding."""

import json
from copy import deepcopy
from types import SimpleNamespace

from app.agents.graph_factory import AgentFactory
from app.agents.supervisor import eligible_actions
from app.harness.evidence import span_source
from app.harness.state import RunScope, RunState
from app.infrastructure.groq.quota import estimate_input_tokens
from app.infrastructure.groq.client import GroqClient


def state():
    return RunState(
        run_id="run", review_id="review", efficient_review=True,
        scope=RunScope(main_paper_id="main", main_version=1,
                       rubric_id="rubric", rubric_version=1,
                       reference_versions={"ref": 1}),
        pending_findings=[{"id": "claim"}], remaining_chunk_ids=["page-2"],
    )


def test_read_and_compare_are_completed_before_verification():
    value = state()
    assert eligible_actions(value) == ["next_batch"]
    value.current_batch_ids = ["page-2"]
    assert eligible_actions(value) == ["analyze"]
    value.current_batch_ids = value.remaining_chunk_ids = []
    assert eligible_actions(value) == ["compare"]
    value.reference_assessments["ref"] = {"status": "assessed"}
    assert eligible_actions(value) == ["verify"]


def context():
    text = "Nghiên cứu sử dụng khảo sát 24 người. Tiếng Việt được giữ nguyên 😀. " * 20
    sources = [span_source({
        "id": "page-1", "paper_id": "main", "content_version": 1,
        "text": text, "locator": {"type": "pdf_page", "value": "1"},
    })]
    span = sources[0]["spans"][0]
    return {
        "scope": state().scope.model_dump(), "chunks": sources,
        "criteria": [{"code": f"unused-{i}", "guidance": "Không liên quan " * 40}
                     for i in range(8)],
        "progress": {"turn_count": 20}, "reference_assessments": {},
        "pending_findings": [{
            "id": f"f-{i}", "kind": "analysis", "criterion_code": "method",
            "claim": f"Quan sát {i}: nghiên cứu khảo sát 24 người.",
            "compared_paper_ids": [], "evidence": [{
                "chunk_id": "page-1", "span_id": span["id"],
                "quote": span["text"], "paper_id": "main", "content_version": 1,
                "locator_type": "pdf_page", "locator_value": "1",
                "start_char": 0, "end_char": len(span["text"]),
            }],
        } for i in range(4)],
    }


def test_verifier_transport_reduces_tokens_and_preserves_all_spans_without_mutation():
    original = context()
    snapshot = deepcopy(original)
    compact, schema = AgentFactory.request(
        "evidence_verifier", SimpleNamespace(evidence_selection_mode=True), original,
    )
    baseline, _ = AgentFactory.request(
        "evidence_verifier", SimpleNamespace(evidence_selection_mode=False), original,
    )
    assert estimate_input_tokens(GroqClient.schema_request(compact, schema)) < (
        estimate_input_tokens(GroqClient.schema_request(baseline, schema)) * 0.75
    )
    model = json.loads(compact[1]["content"])
    assert "criteria" not in model and "scope" not in model
    assert [f["id"] for f in model["pending_findings"]] == [f"f-{i}" for i in range(4)]
    for finding in model["pending_findings"]:
        assert "quote" not in finding["evidence"][0]
    assert [(s["id"], s["text"]) for c in model["chunks"] for s in c["spans"]] == [
        (s["id"], s["text"]) for c in original["chunks"] for s in c["spans"]
    ]
    assert original == snapshot
    assert schema.__name__ == "VerificationOutput"


def test_legacy_quotes_and_omission_mode_remain_available_to_verifier():
    value = context()
    value["omission_audit"] = True
    del value["pending_findings"][0]["evidence"][0]["span_id"]
    messages, _ = AgentFactory.request(
        "evidence_verifier", SimpleNamespace(evidence_selection_mode=True), value,
    )
    model = json.loads(messages[1]["content"])
    assert model["omission_audit"] is True
    assert model["pending_findings"][0]["evidence"][0]["quote"] == (
        value["pending_findings"][0]["evidence"][0]["quote"]
    )


def test_comparison_projection_keeps_both_paper_identities_and_evidence_links():
    value = context()
    related = deepcopy(value["chunks"][0])
    related.update(id="ref-1", paper_id="ref")
    value["chunks"].append(related)
    finding = value["pending_findings"][0]
    finding.update(kind="comparison", compared_paper_ids=["ref"])
    finding["evidence"].append({
        **finding["evidence"][0], "chunk_id": "ref-1", "paper_id": "ref",
    })
    messages, _ = AgentFactory.request(
        "evidence_verifier", SimpleNamespace(evidence_selection_mode=True), value,
    )
    projected = json.loads(messages[1]["content"])
    assert {c["paper_id"] for c in projected["chunks"]} == {"main", "ref"}
    assert projected["pending_findings"][0]["compared_paper_ids"] == ["ref"]
    assert {r["chunk_id"] for r in projected["pending_findings"][0]["evidence"]} == {
        "page-1", "ref-1",
    }
