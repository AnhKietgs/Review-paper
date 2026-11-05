"""Selection-based producers remain subject to provenance and semantic gates."""

import json

from app.agents.schemas import (
    SelectedComparisonOutput, SelectedScientificOutput, VerificationOutput,
)
from app.harness.events import RunEventRecorder
from app.harness.memory import RunMemory
from app.harness.runner import AgentRunner
from app.harness.state import RunScope, RunState
from app.infrastructure.groq.fixture_client import FixtureClient


class Catalog:
    def is_active(self, _paper_id):
        return True

    def chunk(self, chunk_id):
        return {
            "id": chunk_id, "paper_id": "ref" if chunk_id == "ref-1" else "main",
            "content_version": 1,
            "text": "Nghiên cứu khảo sát 24 người.\r\nGiữ nguyên tiếng Việt 😀.",
            "locator": {"type": "pdf_page", "value": "2", "status": "resolved"},
        }

    def chunks(self, paper_id, _version):
        return [self.chunk(f"{paper_id}-1")]

    def criteria(self, _rubric_id, _version):
        return [{"code": "method", "question": "Đánh giá phương pháp", "guidance": ""}]


class SelectionClient(FixtureClient):
    evidence_selection_mode = True

    def generate_json(self, messages, schema):
        if schema not in {SelectedScientificOutput, SelectedComparisonOutput}:
            return super().generate_json(messages, schema)
        context = json.loads(messages[-1]["content"])
        assert all("text" not in chunk for chunk in context["chunks"])
        sources = context["chunks"]
        selections = [
            {"chunk_id": chunk["id"], "span_id": chunk["spans"][0]["id"]}
            for chunk in sources
        ]
        finding = {
            "criterion_code": "method", "claim": "Nguồn mô tả mẫu khảo sát.",
            "kind": "analysis", "evidence": selections,
        }
        if schema is SelectedComparisonOutput:
            finding["kind"] = "comparison"
            finding["compared_paper_ids"] = ["ref"]
            return schema(findings=[finding], assessment="assessed", reason="Hai nguồn")
        return schema(analysis={"objective": "Mô tả mẫu khảo sát"}, findings=[finding])


def execute(client, references=False):
    state = RunState(
        run_id="run", review_id="review", remaining_chunk_ids=["main-1"],
        scope=RunScope(
            main_paper_id="main", main_version=1,
            reference_versions={"ref": 1} if references else {},
            rubric_id="rubric", rubric_version=1,
        ),
    )
    memory, events = RunMemory(), RunEventRecorder()
    memory.save(state)
    runner = AgentRunner(client, Catalog(), memory, events)
    for _ in range(30):
        state = runner.run_turn(state)
        if state.status != "running":
            break
    assert state.status == "completed"
    return state, events


def test_full_selected_flow_resolves_comparison_sources_and_character_positions():
    state, events = execute(SelectionClient(), references=True)
    assert len(state.findings) == 2
    for finding in state.findings:
        assert finding["status"] == "supported"
        for evidence in finding["evidence"]:
            text = Catalog().chunk(evidence["chunk_id"])["text"]
            start, end = evidence["start_char"], evidence["end_char"]
            assert evidence["quote"] == text[start:end]
            assert evidence["span_id"] == "s0"
            assert evidence["locator_value"] == "2"
    comparison = next(f for f in state.findings if f["kind"] == "comparison")
    assert {e["paper_id"] for e in comparison["evidence"]} == {"main", "ref"}
    assert any(e["action"] == "evidence_resolved" for e in events.items)


def test_invented_span_gets_one_source_bound_selection_repair():
    class BadOnce(SelectionClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is SelectedScientificOutput:
                context = json.loads(messages[-1]["content"])
                if "repair_request" not in context:
                    result.findings[0].evidence[0].span_id = "s999"
            return result

    state, events = execute(BadOnce())
    assert state.repair_count == 1
    assert len(state.findings) == 1
    assert state.findings[0]["status"] == "supported"
    assert any(e["action"] == "evidence_resolution_failed" for e in events.items)


def test_invented_span_has_no_fallback_to_whole_chunk():
    class BadAlways(SelectionClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is SelectedScientificOutput:
                result.findings[0].evidence[0].span_id = "s999"
            return result

    state, _ = execute(BadAlways())
    assert state.repair_count == 1
    assert state.findings[0]["status"] == "unsupported"
    assert state.findings[0]["evidence"] == []


def test_exact_source_selection_does_not_override_semantic_rejection():
    class Reject(SelectionClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is VerificationOutput:
                for assessment in result.assessments:
                    assessment.status = "unsupported"
                    assessment.reason = "Nguồn không chứng minh kết luận này."
            return result

    state, _ = execute(Reject())
    assert state.findings[0]["status"] == "unsupported"
    assert state.findings[0]["evidence"][0]["quote"] == (
        Catalog().chunk("main-1")["text"]
    )


def test_groq_producer_contract_only_allows_span_selection_fields():
    from app.infrastructure.groq.client import GroqClient

    assert GroqClient.evidence_selection_mode
    for schema in (SelectedScientificOutput, SelectedComparisonOutput):
        definition = schema.model_json_schema()["$defs"]["EvidenceSelection"]
        assert set(definition["properties"]) == {"chunk_id", "span_id"}
        assert definition["additionalProperties"] is False
