"""On-demand workers, guarded routing and bounded document loop."""

from app.harness.events import RunEventRecorder
from app.harness.memory import RunMemory
from app.harness.runner import AgentRunner
from app.harness.state import RunScope, RunState
from app.infrastructure.groq.fixture_client import FixtureClient
from app.agents.schemas import ScientificOutput, VerificationOutput


class Catalog:
    def is_active(self, _paper_id):
        return True

    def chunk(self, chunk_id):
        paper_id = "ref" if chunk_id.startswith("ref") else "main"
        return {
            "id": chunk_id,
            "paper_id": paper_id,
            "content_version": 1,
            "text": "The sample contains 24 participants.",
            "locator": {"type": "pdf_page", "value": "1", "status": "resolved"},
        }

    def chunks(self, paper_id, _version):
        return [self.chunk(f"{paper_id}-1")]

    def criteria(self, _rubric_id, _version):
        return [{"code": "method", "question": "Assess sample", "guidance": ""}]


def run_state(references=None, chunks=None, **limits):
    return RunState(
        run_id="run",
        review_id="review",
        scope=RunScope(
            main_paper_id="main",
            main_version=1,
            reference_versions=references or {},
            rubric_id="rubric",
            rubric_version=1,
        ),
        remaining_chunk_ids=chunks or ["main-1"],
        **limits,
    )


def execute(state, client=None, catalog=None):
    memory, events = RunMemory(), RunEventRecorder()
    runner = AgentRunner(
        client or FixtureClient(), catalog or Catalog(), memory, events
    )
    memory.save(state)
    while state.status == "running":
        state = runner.run_turn(state)
    return state, events


def test_no_reference_skips_comparator_and_calls_one_worker_per_turn():
    state, events = execute(run_state())
    assert state.status == "completed"
    assert state.call_counts.get("related_work", 0) == 0
    assert state.call_counts["scientific_review"] == 1
    assert state.call_counts["evidence_verifier"] == 1
    workers = [
        item
        for item in events.items
        if item["action"] == "agent_started" and item["agent"] != "supervisor"
    ]
    turns = [item["payload"]["turn"] for item in workers]
    assert len(turns) == len(set(turns))
    assert all(item["status"] == "supported" for item in state.findings)


def test_selected_reference_has_two_sided_evidence():
    state, _ = execute(run_state({"ref": 1}))
    assert state.status == "completed"
    assert state.reference_assessments["ref"]["status"] == "assessed"
    comparisons = [item for item in state.findings if item["kind"] == "comparison"]
    assert comparisons
    assert {source["paper_id"] for source in comparisons[0]["evidence"]} == {
        "main",
        "ref",
    }


def test_invalid_supervisor_action_does_not_call_worker_and_hits_budget():
    state, events = execute(
        run_state(max_turns=3), FixtureClient(force_action="compare")
    )
    assert state.status == "incomplete"
    assert state.call_counts.get("related_work", 0) == 0
    assert state.call_counts.get("evidence_verifier", 0) == 0
    assert any(item["action"] == "agent_skipped" for item in events.items)


def test_document_batch_budget_preserves_unprocessed_ids():
    state, _ = execute(run_state(chunks=[f"main-{i}" for i in range(5)], max_batches=1))
    assert state.status == "incomplete"
    assert len(state.processed_chunk_ids) == 2
    assert len(state.remaining_chunk_ids) == 3


def test_groq_batches_one_page_at_a_time_to_limit_prompt_size():
    state, events = execute(
        run_state(chunks=["main-1", "main-2"], llm_mode="groq")
    )
    batches = [
        item["payload"]["source_ids"]
        for item in events.items if item["action"] == "batch_selected"
    ]
    assert state.status == "completed"
    assert batches == [["main-1"], ["main-2"]]


def test_model_cannot_choose_persisted_finding_ids():
    import json
    from app.agents.schemas import ScientificOutput

    class ReusedIds(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is ScientificOutput:
                for item in result.findings:
                    item.id = "existing-foreign-finding"
            return result

    state, _ = execute(run_state(chunks=["main-1", "main-2"]), ReusedIds())
    assert len({f["id"] for f in state.findings}) == 2
    assert all(f["id"] != "existing-foreign-finding" for f in state.findings)


def test_verifier_rejection_triggers_one_repair_and_reverification():
    class RejectOnce(FixtureClient):
        def __init__(self):
            super().__init__()
            self.verification_calls = 0

        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is VerificationOutput:
                self.verification_calls += 1
                if self.verification_calls == 1:
                    result.assessments[0].status = "unsupported"
                    result.assessments[0].reason = "Claim requires a narrower quote"
            return result

    state, events = execute(run_state(), RejectOnce())
    assert state.status == "completed"
    assert state.repair_count == 1
    assert len(state.findings) == 1
    assert state.findings[0]["status"] == "supported"
    assert any(item["action"] == "finding_repaired" for item in events.items)


def test_invalid_provenance_stays_unverified_after_bounded_repair():
    class StrictCatalog(Catalog):
        def chunk(self, chunk_id):
            if chunk_id == "outside-run":
                return None
            return super().chunk(chunk_id)

    state, events = execute(
        run_state(), FixtureClient(bad_source=True), StrictCatalog()
    )
    assert state.status == "completed"
    assert state.repair_count == 1
    assert len(state.findings) == 1
    assert state.findings[0]["status"] == "unsupported"
    assert state.findings[0]["evidence"] == []
    assert any(item["action"] == "repair_unresolved" for item in events.items)


def test_grounded_question_has_distinct_status_and_source():
    class QuestionClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is ScientificOutput:
                result.findings[0].kind = "question"
                result.findings[0].claim = "How were the 24 participants recruited?"
            return result

    state, _ = execute(run_state(), QuestionClient())
    assert state.status == "completed"
    assert len(state.findings) == 1
    assert state.findings[0]["status"] == "grounded"
    assert state.findings[0]["evidence"][0]["quote"] == (
        "The sample contains 24 participants."
    )


def test_question_without_source_is_omitted_after_bounded_repair():
    class StrictCatalog(Catalog):
        def chunk(self, chunk_id):
            if chunk_id == "outside-run":
                return None
            return super().chunk(chunk_id)

    class BadQuestionClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is ScientificOutput:
                result.findings[0].kind = "question"
                result.findings[0].claim = "How were the 24 participants recruited?"
            return result

    state, events = execute(
        run_state(), BadQuestionClient(bad_source=True), StrictCatalog()
    )
    assert state.status == "completed"
    assert state.repair_count == 1
    assert state.findings == []
    assert any(item["action"] == "repair_unresolved" for item in events.items)
    assert any(item["action"] == "question_omitted" for item in events.items)


def test_question_rejected_by_verifier_is_omitted_after_one_repair():
    class RejectedQuestionClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is ScientificOutput:
                result.findings[0].kind = "question"
                result.findings[0].claim = "How were participants recruited?"
            if schema is VerificationOutput:
                for assessment in result.assessments:
                    assessment.status = "unsupported"
                    assessment.reason = "Passage does not ground this question"
            return result

    state, events = execute(run_state(), RejectedQuestionClient())
    assert state.status == "completed"
    assert state.repair_count == 1
    assert state.findings == []
    assert any(item["action"] == "question_omitted" for item in events.items)
