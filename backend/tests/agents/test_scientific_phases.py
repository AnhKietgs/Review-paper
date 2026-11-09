"""Two-phase scientific contracts and phase order remain evidence grounded."""

import json
from types import SimpleNamespace
import pytest

from app.agents.graph_factory import AgentFactory
from app.agents.supervisor import eligible_actions
from app.harness.state import RunScope, RunState
from app.harness.evidence import span_source
from app.agents.schemas import ExtractionOutput, SelectedScientificOutput
from app.harness.runner import AgentRunner
from app.harness.memory import RunMemory
from app.harness.events import RunEventRecorder
from app.infrastructure.groq.fixture_client import FixtureClient
from app.agents.ports import RateLimitPause


def source():
    return {"id": "main-1", "paper_id": "main", "content_version": 1,
            "text": "Nghiên cứu khảo sát 24 người. Giữ nguyên tiếng Việt 😀.",
            "locator": {"type": "pdf_page", "value": "1", "status": "resolved"}}


def state():
    return RunState(run_id="run", review_id="review", two_phase_review=True,
                    efficient_review=True,
                    scope=RunScope(main_paper_id="main", main_version=1,
                                   rubric_id="rubric", rubric_version=1),
                    remaining_chunk_ids=["main-1"])


def context(phase):
    return {"scientific_phase": phase, "scope": state().scope.model_dump(),
            "chunks": [span_source(source())],
            "criteria": [{"code": "method", "question": "Phương pháp?"}],
            "pending_findings": [], "notes": [], "reference_assessments": {}}


def test_extract_contract_is_short_and_synthesis_is_separate_action():
    messages, schema = AgentFactory.request(
        "scientific_review", SimpleNamespace(evidence_selection_mode=True),
        context("extract"),
    )
    assert schema.__name__ == "ExtractionOutput"
    assert "findings" not in schema.model_json_schema()["properties"]
    value = state()
    assert eligible_actions(value) == ["next_batch"]
    value.remaining_chunk_ids = []
    value.processed_chunk_ids = ["main-1"]
    assert eligible_actions(value) == ["synthesize"]
    value.scientific_synthesized = True
    assert eligible_actions(value) == ["finish"]
    assert json.loads(messages[1]["content"])["chunks"][0]["spans"][0]["id"] == "s0"


class Catalog:
    def chunk(self, chunk_id):
        return {**source(), "id": chunk_id}

    def is_active(self, _paper):
        return True

    def criteria(self, *_args):
        return [{"code": "method", "question": "Phương pháp?"}]


class ScientificClient(FixtureClient):
    evidence_selection_mode = True

    def __init__(self, bad=False):
        super().__init__()
        self.phases, self.bad = [], bad

    def generate_json(self, messages, schema):
        value = json.loads(messages[1]["content"])
        if schema is ExtractionOutput:
            self.phases.append("extract")
            chunk = value["chunks"][0]
            return schema(notes=[{
                "criterion_code": "method", "text": "Nghiên cứu khảo sát 24 người.",
                "evidence": [{"chunk_id": chunk["id"], "span_id":
                              "fake-span" if self.bad else chunk["spans"][0]["id"]}],
            }])
        if schema is SelectedScientificOutput:
            self.phases.append("synthesize")
            assert value["notes"] and value["chunks"]
            assert all("quote" not in r for n in value["notes"] for r in n["evidence"])
            return schema(analysis={"objective": "Khảo sát 24 người."}, findings=[{
                "criterion_code": "method", "kind": "analysis",
                "claim": "Nghiên cứu khảo sát 24 người.",
                "evidence": [value["notes"][0]["evidence"][0]],
            }])
        return super().generate_json(messages, schema)


def run(client):
    value = state()
    value.remaining_chunk_ids = ["main-1", "main-2"]
    value.llm_mode = "groq"
    memory, events = RunMemory(), RunEventRecorder()
    runner = AgentRunner(client, Catalog(), memory, events)
    memory.save(value)
    for _ in range(30):
        value = runner.run_turn(value)
        if value.status != "running":
            break
    return value


def test_two_phase_flow_resolves_notes_then_verifies_original_source():
    client = ScientificClient()
    result = run(client)
    assert result.status == "completed"
    assert client.phases == ["extract", "extract", "synthesize"]
    assert len(result.read_notes) == 2
    assert result.scientific_synthesized
    assert result.findings[0]["status"] == "supported"
    evidence = result.findings[0]["evidence"][0]
    assert evidence["quote"] == source()["text"]
    assert evidence["start_char"] == 0
    assert result.call_counts["supervisor"] == 1
    assert set(result.call_counts) <= {"supervisor", "scientific_review", "evidence_verifier"}


def test_invalid_note_source_does_not_become_a_synthesis_claim():
    client = ScientificClient(bad=True)
    result = run(client)
    assert result.status == "incomplete"
    assert result.error_code == "scientific_notes_unavailable"
    assert result.read_notes == [] and result.findings == []
    assert client.phases == ["extract", "extract"]
    assert "chưa đánh giá" in result.analysis["limitations"][0]


@pytest.mark.parametrize("pause_phase", ["extract", "synthesize"])
def test_partial_phase_resume_reuses_completed_calls_and_original_offsets(pause_phase):
    class LongCatalog(Catalog):
        def chunk(self, chunk_id):
            return {**super().chunk(chunk_id), "text": source()["text"] * 180}

    class PausingClient(ScientificClient):
        paused = False

        def __init__(self):
            super().__init__()
            self.completed = {"extract": [], "synthesize": []}

        def fits_request(self, messages, _schema):
            return len(messages[1]["content"].encode()) <= 4000

        def generate_json(self, messages, schema):
            value = json.loads(messages[1]["content"])
            phase = value.get("scientific_phase")
            if phase:
                if phase == pause_phase and self.completed[phase] and not self.paused:
                    self.paused = True
                    raise RateLimitPause(60)
                signature = tuple(
                    s["id"] for c in value["chunks"] for s in c["spans"]
                ) if phase == "extract" else tuple(n["id"] for n in value["notes"])
                assert signature not in self.completed[phase]
                result = super().generate_json(messages, schema)
                self.completed[phase].append(signature)
                return result
            return super().generate_json(messages, schema)

    value = state()
    value.current_batch_ids = ["main-1"]
    memory, events, client, catalog = RunMemory(), RunEventRecorder(), PausingClient(), LongCatalog()
    memory.save(value)
    runner = AgentRunner(client, catalog, memory, events)
    with pytest.raises(RateLimitPause):
        for _ in range(20):
            value = runner.run_turn(value)
    saved = memory.load(value.run_id)
    assert saved.turn_progress.context["scientific_phase"] == pause_phase
    assert len(saved.turn_progress.work_outputs) == 1
    assert not saved.scientific_synthesized
    runner = AgentRunner(client, catalog, memory, events)
    value = saved
    for _ in range(100):
        value = runner.run_turn(value)
        if value.status != "running":
            break
    assert value.status == "completed"
    assert len(value.read_notes) > 1
    for finding in value.findings:
        for evidence in finding["evidence"]:
            original = catalog.chunk(evidence["chunk_id"])["text"]
            assert original[evidence["start_char"]:evidence["end_char"]] == evidence["quote"]
