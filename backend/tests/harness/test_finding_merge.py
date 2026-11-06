"""Conservative consolidation before repair and semantic verification."""

from copy import deepcopy
import unicodedata

import pytest

from app.harness.events import RunEventRecorder
from app.agents.schemas import ScientificOutput, VerificationOutput
from app.harness.finding_merge import finding_key
from app.harness.memory import RunMemory
from app.harness.runner import AgentRunner
from app.harness.state import RunScope, RunState
from app.harness.tool_gateway import ToolGateway
from app.infrastructure.groq.fixture_client import FixtureClient


class Catalog:
    """Two real source locations with identical extracted text."""

    def is_active(self, _paper_id):
        return True

    def chunk(self, chunk_id):
        return {
            "id": chunk_id,
            "paper_id": "main",
            "content_version": 1,
            "text": "The sample contains 24 participants.",
            "locator": {"type": "pdf_page", "value": chunk_id, "status": "resolved"},
        }

    def criteria(self, *_args):
        return [{"code": "method", "question": "Assess methodology"}]


def draft(finding_id="first", chunk_id="page-1", **changes):
    result = {
        "id": finding_id,
        "criterion_code": "method",
        "kind": "analysis",
        "claim": "Nghiên cứu sử dụng 24 người tham gia.",
        "compared_paper_ids": [],
        "evidence": [{
            "paper_id": "main", "content_version": 1, "chunk_id": chunk_id,
            "quote": "The sample contains 24 participants.",
            "locator_type": "pdf_page", "locator_value": chunk_id,
        }],
    }
    result.update(changes)
    return result


@pytest.fixture
def harness():
    state = RunState(
        run_id="run", review_id="review",
        scope=RunScope(
            main_paper_id="main", main_version=1,
            rubric_id="rubric", rubric_version=1,
        ),
    )
    runner = AgentRunner(
        FixtureClient(), Catalog(), RunMemory(), RunEventRecorder(),
    )
    return runner, state


def stage(runner, state, *findings):
    runner._stage(state, list(findings), "scientific_review", ["page-1"])


def verify(runner, state):
    runner._verify(state, ToolGateway(runner.catalog, runner.events, state.run_id))


def test_criterion_cap_counts_all_queues_but_still_merges_evidence(harness):
    runner, state = harness
    state.max_findings_per_criterion = 2
    stage(runner, state, draft(), draft(claim="Mẫu được tuyển tại một trường."))
    canonical_id = state.pending_findings[0]["id"]
    stage(runner, state, draft("other", "page-2"))
    assert state.pending_findings[0]["id"] == canonical_id
    assert len(state.pending_findings[0]["evidence"]) == 2
    stage(runner, state, draft(claim="không nêu cỡ mẫu", kind="omission"))
    assert not state.omission_audits
    assert len(state.pending_findings) == 2
    assert runner.events.items[-1]["action"] == "finding_limit_reached"


def test_duplicates_merge_sources_and_preserve_first_system_id(harness):
    runner, state = harness
    stage(runner, state, draft())
    canonical_id = state.pending_findings[0]["id"]
    repeated = unicodedata.normalize("NFD", draft()["claim"].upper())
    stage(runner, state, draft("second", "page-2", claim=f"  {repeated}\n"))
    assert len(state.pending_findings) == 1
    assert state.pending_findings[0]["id"] == canonical_id
    assert len(state.pending_findings[0]["evidence"]) == 2
    verify(runner, state)
    assert len(state.findings) == 1
    assert state.call_counts["evidence_verifier"] == 1
    merged = [e for e in runner.events.items if e["action"] == "findings_merged"]
    assert merged[0]["payload"]["canonical_finding_id"] == canonical_id


def test_repeat_after_checkpoint_does_not_reopen_verified_finding(harness):
    runner, state = harness
    stage(runner, state, draft())
    verify(runner, state)
    runner.memory.save(state)
    restored = runner.memory.load(state.run_id)
    before = deepcopy(restored.findings)
    stage(runner, restored, draft("duplicate"))
    assert restored.pending_findings == []
    assert restored.findings == before
    assert restored.repair_queue == []


def test_new_evidence_reopens_same_id_without_stale_verdict(harness):
    runner, state = harness
    stage(runner, state, draft())
    verify(runner, state)
    canonical_id = state.findings[0]["id"]
    stage(runner, state, draft("new", "page-2"))
    assert state.findings == []
    assert len(state.pending_findings) == 1
    assert state.pending_findings[0]["id"] == canonical_id
    assert "status" not in state.pending_findings[0]
    assert "verdict" not in state.pending_findings[0]
    verify(runner, state)
    assert len(state.findings) == 1
    assert state.call_counts["evidence_verifier"] == 2


def test_invalid_duplicate_cannot_poison_supported_evidence(harness):
    runner, state = harness
    stage(runner, state, draft())
    verify(runner, state)
    invalid = draft("bad", "page-2")
    invalid["evidence"][0]["quote"] = "Invented quote"
    before = deepcopy(state.findings)
    stage(runner, state, invalid)
    assert state.findings == before
    assert not state.pending_findings
    assert not state.repair_queue


@pytest.mark.parametrize("changes", [
    {"criterion_code": "results"},
    {"kind": "strength"},
    {"claim": "Nghiên cứu sử dụng 25 người tham gia."},
    {"claim": "Nghiên cứu không sử dụng 24 người tham gia."},
    {"claim": "Nghiên cứu sử dụng 24 người tham gia?"},
    {"compared_paper_ids": ["other"]},
])
def test_distinct_keys_are_never_merged(harness, changes):
    runner, state = harness
    stage(runner, state, draft(), draft("second", **changes))
    assert len(state.pending_findings) == 2


def test_invalid_duplicates_share_one_repair(harness):
    runner, state = harness
    bad = draft(evidence=[])
    stage(runner, state, bad, bad, bad)
    assert len(state.findings) == 1
    assert len(state.repair_queue) == 1
    assert state.call_counts.get("evidence_verifier", 0) == 0


def test_restored_pending_duplicates_are_consolidated_before_verify(harness):
    runner, state = harness
    state.pending_findings = [draft(), draft("second", "page-2")]
    runner.memory.save(state)
    restored = runner.memory.load(state.run_id)
    verify(runner, restored)
    assert len(restored.findings) == 1
    assert restored.findings[0]["id"] == "first"
    assert len(restored.findings[0]["evidence"]) == 2


def test_omission_duplicates_do_not_reset_audit_progress(harness):
    runner, state = harness
    stage(runner, state, draft(kind="omission", evidence=[]))
    state.omission_audits[0]["checked"] = 2
    stage(runner, state, draft(
        "second", kind="omission", evidence=[],
        claim="  NGHIÊN CỨU SỬ DỤNG 24 NGƯỜI THAM GIA.  ",
    ))
    assert len(state.omission_audits) == 1
    assert state.omission_audits[0]["checked"] == 2


def test_comparison_key_ignores_reference_order_and_duplicate_ids():
    assert finding_key(draft(compared_paper_ids=["a", "b", "a"])) == (
        finding_key(draft(compared_paper_ids=["b", "a"]))
    )


def test_duplicate_rejection_uses_one_repair_and_keeps_canonical_id(harness):
    class RejectOnce(FixtureClient):
        def __init__(self):
            super().__init__()
            self.verifications = 0

        def generate_json(self, messages, schema):
            output = super().generate_json(messages, schema)
            if schema is VerificationOutput:
                self.verifications += 1
                if self.verifications == 1:
                    for item in output.assessments:
                        item.status = "unsupported"
            if schema is ScientificOutput:
                output.findings[0].claim = draft()["claim"]
            return output

    runner, state = harness
    runner.llm = RejectOnce()
    stage(runner, state, draft(), draft("duplicate"), draft("third"))
    canonical_id = state.pending_findings[0]["id"]
    verify(runner, state)
    assert len(state.repair_queue) == 1
    runner._repair(
        state, ToolGateway(runner.catalog, runner.events, state.run_id),
    )
    verify(runner, state)
    assert state.repair_count == 1
    assert len(state.findings) == 1
    assert state.findings[0]["id"] == canonical_id
    assert state.findings[0]["status"] == "supported"
    assert state.call_counts["evidence_verifier"] == 2


def test_repair_matching_another_verified_claim_is_not_verified_again(harness):
    class RepairSame(FixtureClient):
        def generate_json(self, messages, schema):
            output = super().generate_json(messages, schema)
            if schema is ScientificOutput:
                output.findings[0].claim = draft()["claim"]
            return output

    runner, state = harness
    runner.llm = RepairSame()
    stage(runner, state, draft())
    verify(runner, state)
    canonical_id = state.findings[0]["id"]
    stage(runner, state, draft(
        "bad", claim="Another unverified claim.", evidence=[],
    ))
    runner._repair(
        state, ToolGateway(runner.catalog, runner.events, state.run_id),
    )
    assert state.pending_findings == []
    assert state.repair_queue == []
    assert len(state.findings) == 1
    assert state.findings[0]["id"] == canonical_id
    assert state.call_counts["evidence_verifier"] == 1


def test_same_supported_source_repeated_in_next_turn_skips_verifier(harness):
    runner, state = harness
    state.current_batch_ids = ["page-1"]
    gateway = ToolGateway(runner.catalog, runner.events, state.run_id)
    runner._analyze(state, gateway)
    verify(runner, state)
    runner.memory.save(state)
    state = runner.memory.load(state.run_id)
    state.current_batch_ids = ["page-1"]
    runner._analyze(state, gateway)
    assert not state.pending_findings
    assert state.call_counts["scientific_review"] == 2
    assert state.call_counts["evidence_verifier"] == 1
    assert len(state.findings) == 1


def test_partial_comparison_sources_can_complete_one_canonical_finding(harness):
    class ComparisonCatalog(Catalog):
        def chunk(self, chunk_id):
            result = super().chunk(chunk_id)
            if chunk_id.startswith("ref"):
                result["paper_id"] = "ref"
            return result

    runner, state = harness
    runner.catalog = ComparisonCatalog()
    runner.output_gate.catalog = runner.catalog
    state.scope.reference_versions = {"ref": 1}
    left = draft(kind="comparison", compared_paper_ids=["ref"])
    stage(runner, state, left)
    canonical_id = state.findings[0]["id"]
    right = draft("second", "ref-1", kind="comparison", compared_paper_ids=["ref"])
    right["evidence"][0]["paper_id"] = "ref"
    stage(runner, state, right)
    assert state.findings == []
    assert len(state.pending_findings) == 1
    assert state.pending_findings[0]["id"] == canonical_id
    assert {e["paper_id"] for e in state.pending_findings[0]["evidence"]} == {
        "main", "ref",
    }
    assert state.repair_queue == []


def test_evidence_whitespace_variation_does_not_trigger_reverification(harness):
    runner, state = harness
    stage(runner, state, draft())
    verify(runner, state)
    repeat = draft("second")
    repeat["evidence"][0]["quote"] = "The sample  contains 24 participants."
    stage(runner, state, repeat)
    assert state.pending_findings == []
    assert len(state.findings) == 1


def test_restored_duplicate_sanitizes_canonical_with_mixed_bad_sources(harness):
    runner, state = harness
    canonical = draft()
    bad = draft("bad", "page-2")["evidence"][0]
    bad["quote"] = "Invented quote"
    canonical["evidence"].append(bad)
    state.pending_findings = [canonical, draft("second")]
    runner.memory.save(state)
    restored = runner.memory.load(state.run_id)
    verify(runner, restored)
    assert len(restored.findings) == 1
    assert restored.findings[0]["status"] == "supported"
    assert len(restored.findings[0]["evidence"]) == 1
    assert not restored.repair_queue


def test_recovered_sources_do_not_consume_an_unexecuted_repair(harness):
    class Reject(FixtureClient):
        def generate_json(self, messages, schema):
            output = super().generate_json(messages, schema)
            if schema is VerificationOutput:
                output.assessments[0].status = "unsupported"
            return output

    runner, state = harness
    runner.llm = Reject()
    stage(runner, state, draft(evidence=[]))
    canonical_id = state.findings[0]["id"]
    assert len(state.repair_queue) == 1
    stage(runner, state, draft("recovered"))
    assert state.repair_queue == []
    verify(runner, state)
    assert state.repair_count == 0
    assert len(state.repair_queue) == 1
    assert state.repair_queue[0]["finding_id"] == canonical_id


def test_new_sources_do_not_reset_an_executed_repair_budget(harness):
    runner, state = harness
    stage(runner, state, draft())
    verify(runner, state)
    canonical_id = state.findings[0]["id"]
    state.repair_attempted_ids = [canonical_id]
    state.repair_count = 1
    stage(runner, state, draft("new", "page-2"))
    assert state.repair_attempted_ids == [canonical_id]
    assert state.repair_count == 1
