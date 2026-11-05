"""On-demand workers, guarded routing and bounded document loop."""

import json

import pytest

from app.harness.events import RunEventRecorder
from app.harness.memory import RunMemory
from app.harness.runner import AgentRunner
from app.harness.state import RunScope, RunState
from app.infrastructure.groq.fixture_client import FixtureClient
from app.agents.ports import LLMFailure, RateLimitPause
from app.agents.schemas import (
    AgentAction, ComparisonOutput, ScientificOutput, VerificationOutput,
)


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


def test_groq_comparison_batches_keep_both_sources_and_all_selected_pages():
    class TwoPageCatalog(Catalog):
        def chunks(self, paper_id, _version):
            return [self.chunk(f"{paper_id}-{index}") for index in (1, 2)]

    class BoundedComparator(FixtureClient):
        def __init__(self):
            super().__init__()
            self.groups = []

        def generate_json(self, messages, schema):
            context = json.loads(messages[-1]["content"])
            if schema is ComparisonOutput:
                chunks = context["chunks"]
                if len(chunks) > 2:
                    raise LLMFailure("quota_request_too_large")
                assert {item["paper_id"] for item in chunks} == {"main", "ref"}
                self.groups.append([item["id"] for item in chunks])
            return super().generate_json(messages, schema)

    client = BoundedComparator()
    state, _ = execute(
        run_state({"ref": 1}, chunks=["main-1", "main-2"], llm_mode="groq"),
        client, TwoPageCatalog(),
    )
    assert state.status == "completed"
    assert client.groups == [["main-1", "ref-1"], ["main-2", "ref-2"]]
    assert state.reference_assessments["ref"]["chunk_ids"] == ["ref-1", "ref-2"]
    assert state.call_counts["related_work"] == 2


def test_comparison_batch_cursor_survives_checkpoint_reload():
    state = run_state({"ref": 1}, llm_mode="groq")
    state.remaining_chunk_ids = []
    state.processed_chunk_ids = ["main-1", "main-2"]
    memory, events = RunMemory(), RunEventRecorder()
    runner = AgentRunner(FixtureClient(), Catalog(), memory, events)
    memory.save(state)
    state = runner.run_turn(state)
    state = memory.load(state.run_id)
    assert "ref" not in state.reference_assessments
    assert state.comparison_progress["ref"]["cursor"] == 1
    state, _ = execute(state)
    assert state.status == "completed"
    comparisons = [f for f in state.findings if f["kind"] == "comparison"]
    assert len(comparisons) == 2


def test_reference_deleted_between_comparison_batches_is_skipped():
    class MutableCatalog(Catalog):
        reference_available = True

        def is_active(self, paper_id):
            return paper_id != "ref" or self.reference_available

    state = run_state({"ref": 1}, llm_mode="groq")
    state.remaining_chunk_ids = []
    state.processed_chunk_ids = ["main-1", "main-2"]
    catalog = MutableCatalog()
    memory, events = RunMemory(), RunEventRecorder()
    memory.save(state)
    runner = AgentRunner(FixtureClient(), catalog, memory, events)
    state = runner.run_turn(state)  # First comparison pair.
    state = runner.run_turn(state)  # Verify its finding.
    catalog.reference_available = False
    state = runner.run_turn(state)
    assert state.reference_assessments["ref"]["status"] == "not_assessed"
    assert "ref" not in state.comparison_progress


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


def test_contribution_bad_quote_gets_one_source_bound_repair():
    class ContributionClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is ScientificOutput:
                context = json.loads(messages[-1]["content"])
                result.findings[0].criterion_code = "contribution"
                result.findings[0].claim = "The author proposes an AI model."
                if "repair_request" not in context:
                    result.findings[0].evidence[0].quote = "not an exact quote"
            return result

    state, events = execute(run_state(), ContributionClient())
    assert state.status == "completed"
    assert state.repair_count == 1
    assert len(state.findings) == 1
    assert state.findings[0]["criterion_code"] == "contribution"
    assert state.findings[0]["status"] == "supported"
    assert any(item["action"] == "finding_repaired" for item in events.items)


def test_omission_is_deferred_until_full_document_audit():
    class OmissionClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            context = json.loads(messages[-1]["content"])
            if schema is ScientificOutput:
                result.findings = (
                    result.findings[:1]
                    if context["chunks"][0]["id"] == "main-1" else []
                )
                if not result.findings:
                    return result
                result.findings[0].kind = "omission"
                result.findings[0].claim = "quy trình đánh giá mô hình"
                result.findings[0].evidence = []
            if schema is VerificationOutput and context.get("omission_audit"):
                result.assessments[0].status = "unsupported"
                result.assessments[0].reason = "No evaluation procedure in these chunks"
            return result

    state, events = execute(
        run_state(chunks=["main-1", "main-2", "main-3"]),
        OmissionClient(),
    )
    assert state.status == "completed"
    assert len(state.findings) == 1
    assert state.findings[0]["status"] == "not_reported"
    assert "v1" in state.findings[0]["claim"]
    audits = [item for item in events.items if item["action"] == "omission_audited"]
    assert len(audits) == 2
    assert {chunk for event in audits for chunk in event["payload"]["source_ids"]} == {
        "main-1", "main-2", "main-3",
    }


@pytest.mark.parametrize("detail_found", [False, True])
def test_unmentioned_ethics_limitation_requires_full_paper_audit(detail_found):
    class EthicsClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            context = json.loads(messages[-1]["content"])
            if schema is ScientificOutput:
                result.findings = (
                    result.findings[:1]
                    if context["chunks"][0]["id"] == "main-1" else []
                )
                if result.findings:
                    finding = result.findings[0]
                    finding.kind = "limitation"
                    finding.claim = (
                        "Bài báo không đề cập đến các hạn chế hoặc rủi ro đạo đức "
                        "liên quan đến việc sử dụng AI trong giáo dục ngôn ngữ."
                    )
                    finding.evidence = []
            if schema is VerificationOutput and context.get("omission_audit"):
                result.assessments[0].status = (
                    "supported"
                    if detail_found and context["chunks"][-1]["id"] == "main-3"
                    else "unsupported"
                )
            return result

    state, events = execute(
        run_state(chunks=["main-1", "main-2", "main-3"]), EthicsClient()
    )
    assert state.status == "completed"
    audits = [e for e in events.items if e["action"] == "omission_audited"]
    assert {chunk for e in audits for chunk in e["payload"]["source_ids"]} == {
        "main-1", "main-2", "main-3",
    }
    assert state.repair_count == 0
    if detail_found:
        assert state.findings == []
    else:
        assert len(state.findings) == 1
        assert state.findings[0]["kind"] == "omission"
        assert state.findings[0]["status"] == "not_reported"
        assert "sau khi rà soát 3 đoạn" in state.findings[0]["claim"]


def test_omission_found_on_later_page_is_not_published():
    class DetailFound(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            context = json.loads(messages[-1]["content"])
            if schema is ScientificOutput:
                result.findings = (
                    result.findings[:1]
                    if context["chunks"][0]["id"] == "main-1" else []
                )
                if not result.findings:
                    return result
                result.findings[0].kind = "omission"
                result.findings[0].claim = "quy trình đánh giá mô hình"
                result.findings[0].evidence = []
            if schema is VerificationOutput and context.get("omission_audit"):
                result.assessments[0].status = (
                    "supported" if context["chunks"][-1]["id"] == "main-3"
                    else "unsupported"
                )
            return result

    state, events = execute(
        run_state(chunks=["main-1", "main-2", "main-3"]), DetailFound()
    )
    assert state.status == "completed"
    assert state.findings == []
    assert any(item["action"] == "omission_refuted" for item in events.items)


@pytest.mark.parametrize("wording", ["cung cấp", "đề cập đến"])
def test_incomplete_paper_never_publishes_omission(wording):
    class OmissionClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            if schema is ScientificOutput:
                result.findings = result.findings[:1]
                result.findings[0].kind = "limitation"
                result.findings[0].claim = (
                    f"Bài báo không {wording} thông tin chi tiết về "
                    "quy trình đánh giá mô hình."
                )
            return result

    state, events = execute(
        run_state(chunks=["main-1", "main-2", "main-3"], max_batches=1),
        OmissionClient(),
    )
    assert state.status == "incomplete"
    assert not any(item["status"] == "not_reported" for item in state.findings)
    assert len(state.omission_audits) == 1
    assert state.omission_audits[0]["finding"]["kind"] == "omission"
    assert not any(item["action"] == "omission_audited" for item in events.items)


def test_ambiguous_omission_audit_stays_uncertain():
    class AmbiguousClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            context = json.loads(messages[-1]["content"])
            if schema is ScientificOutput:
                result.findings[0].kind = "omission"
                result.findings[0].claim = "quy trình đánh giá mô hình"
                result.findings[0].evidence = []
            if schema is VerificationOutput and context.get("omission_audit"):
                result.assessments[0].status = "uncertain"
            return result

    state, _ = execute(run_state(), AmbiguousClient())
    assert state.status == "completed"
    assert state.findings[0]["kind"] == "omission"
    assert state.findings[0]["status"] == "uncertain"
    assert state.findings[0]["claim"].startswith("Chưa thể kết luận")


def test_invalid_supervisor_json_uses_only_eligible_action():
    class InvalidSupervisor(FixtureClient):
        def generate_json(self, messages, schema):
            if schema is AgentAction:
                raise LLMFailure("invalid_model_output")
            return super().generate_json(messages, schema)

    state, events = execute(run_state({"ref": 1}), InvalidSupervisor())
    assert state.status == "completed"
    assert state.reference_assessments["ref"]["status"] == "assessed"
    decisions = [
        item["payload"]["selected_action"] for item in events.items
        if item["action"] == "decision"
    ]
    assert "compare" in decisions
    assert "finish" in decisions
    assert any(item["action"] == "supervisor_fallback" for item in events.items)


def test_supervisor_rate_limit_suspends_turn_instead_of_falling_back():
    class RateLimitedClient(FixtureClient):
        def generate_json(self, _messages, _schema):
            raise RateLimitPause(60)

    state = run_state()
    memory, events = RunMemory(), RunEventRecorder()
    runner = AgentRunner(RateLimitedClient(), Catalog(), memory, events)
    memory.save(state)

    import pytest

    with pytest.raises(RateLimitPause):
        runner.run_turn(state)

    assert not any(item["action"] == "supervisor_fallback" for item in events.items)
    assert not any(
        item["action"] == "agent_started"
        and item["agent"] == "scientific_review"
        for item in events.items
    )


def test_omission_topics_share_each_document_scan():
    class SeveralTopics(FixtureClient):
        def __init__(self):
            super().__init__()
            self.audit_sizes = []

        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            context = json.loads(messages[-1]["content"])
            if schema is ScientificOutput:
                if context["chunks"][0]["id"] != "main-1":
                    result.findings = []
                else:
                    original = result.findings[0]
                    result.findings = []
                    for topic in ("tuyển mẫu", "đánh giá", "đạo đức"):
                        finding = original.model_copy(deep=True)
                        finding.kind = "omission"
                        finding.claim = topic
                        finding.evidence = []
                        result.findings.append(finding)
            if schema is VerificationOutput and context.get("omission_audit"):
                self.audit_sizes.append(len(context["pending_findings"]))
                for assessment in result.assessments:
                    assessment.status = "unsupported"
            return result

    client = SeveralTopics()
    state, _ = execute(
        run_state(chunks=["main-1", "main-2", "main-3"]), client
    )
    assert state.status == "completed"
    assert client.audit_sizes == [3, 3]
    assert len(state.findings) == 3


def test_invalid_omission_audit_does_not_claim_detail_is_absent():
    class InvalidAudit(FixtureClient):
        def generate_json(self, messages, schema):
            context = json.loads(messages[-1]["content"])
            if schema is VerificationOutput and context.get("omission_audit"):
                raise LLMFailure("invalid_model_output")
            result = super().generate_json(messages, schema)
            if schema is ScientificOutput:
                result.findings[0].kind = "omission"
                result.findings[0].claim = "quy trình đánh giá mô hình"
                result.findings[0].evidence = []
            return result

    state, events = execute(run_state(), InvalidAudit())
    assert state.status == "completed"
    assert state.findings[0]["status"] == "uncertain"
    assert "không tìm thấy" not in state.findings[0]["claim"].lower()
    assert any(
        item["action"] == "omission_audit_unavailable" for item in events.items
    )
