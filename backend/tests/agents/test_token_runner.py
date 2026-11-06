"""Full source-position flow with exact adapter budgets and fake completions."""

import json
from types import SimpleNamespace

import pytest

from app.agents.ports import RateLimitPause
from app.harness.events import RunEventRecorder
from app.harness.memory import RunMemory
from app.harness.runner import AgentRunner
from app.harness.state import RunScope, RunState
from app.infrastructure.groq.client import GroqClient
from app.infrastructure.groq.quota import GroqQuota, estimate_input_tokens
from app.infrastructure.groq.router import GroqRouter


class Catalog:
    text = "Phương pháp khảo sát 24 người tham gia. Kết quả tiếng Việt 😀.\n" * 100

    def chunk(self, chunk_id):
        return {
            "id": chunk_id, "paper_id": "main", "content_version": 1,
            "text": self.text,
            "locator": {"type": "pdf_page", "value": "7", "status": "resolved"},
        }

    def is_active(self, _paper_id):
        return True

    def criteria(self, *_args):
        return [{"code": "method", "question": "Đánh giá phương pháp"}]


def test_token_sized_calls_resume_only_unfinished_work_and_keep_source_offsets():
    attempts, completed = [], []
    paused = []
    clock = [0.0]
    quota = GroqQuota(
        tokens_per_minute=8000, requests_per_minute=1000, clock=lambda: clock[0],
    )

    def sleep(seconds):
        clock[0] += seconds

    def completion(**kwargs):
        context = json.loads(kwargs["messages"][1]["content"])
        role = kwargs["model"]
        assert estimate_input_tokens(kwargs["messages"]) + kwargs["max_completion_tokens"] <= 8000
        attempts.append(role)
        if role == "supervisor":
            result = {"action": context["allowed_actions"][0], "reason": "Test"}
        elif role == "scientific_review":
            ids = tuple(s["id"] for c in context["chunks"] for s in c["spans"])
            if completed and not paused:
                paused.append(True)
                raise RateLimitPause(60)
            assert ids not in completed
            completed.append(ids)
            result = {"analysis": {"objective": "Khảo sát"}, "findings": [
                {
                    "criterion_code": "method", "kind": "analysis",
                    "claim": f"Quan sát từ {span['id']}",
                    "evidence": [{"chunk_id": c["id"], "span_id": span["id"]}],
                } for c in context["chunks"] for span in c["spans"]
            ]}
        else:
            result = {"assessments": [
                {"finding_id": f["id"], "status": "supported", "reason": "Nguồn hỗ trợ"}
                for f in context["pending_findings"]
            ]}
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))],
            usage=SimpleNamespace(total_tokens=10),
        )

    router = GroqRouter({role: GroqClient(
        "fake", role, completion=completion, quota=quota,
        max_completion_tokens=budget, sleep=sleep,
    ) for role, budget in [
        ("supervisor", 256), ("scientific_review", 3072), ("evidence_verifier", 4096),
    ]})
    state = RunState(
        run_id="run", review_id="review", remaining_chunk_ids=["main-1"],
        current_batch_ids=["main-1"],
        max_findings_per_criterion=20,
        scope=RunScope(
            main_paper_id="main", main_version=1, rubric_id="rubric", rubric_version=1,
        ),
    )
    memory, events = RunMemory(), RunEventRecorder()
    memory.save(state)
    runner = AgentRunner(router, Catalog(), memory, events)
    with pytest.raises(RateLimitPause):
        runner.run_turn(state)
    state = memory.load(state.run_id)
    assert len(state.turn_progress.work_outputs) == 1
    assert state.processed_chunk_ids == []
    assert attempts.count("supervisor") == 1
    runner = AgentRunner(router, Catalog(), memory, events)
    state = runner.run_turn(state)
    assert attempts.count("supervisor") == 1
    assert state.processed_chunk_ids == ["main-1"]
    for _ in range(10):
        state = runner.run_turn(state)
        if state.status != "running":
            break
    assert state.status == "completed"
    assert len(completed) > 1
    assert attempts.count("evidence_verifier") > 1
    for finding in state.findings:
        assert finding["status"] == "supported"
        for reference in finding["evidence"]:
            assert reference["chunk_id"] == "main-1"
            assert reference["locator_value"] == "7"
            assert reference["quote"] == Catalog.text[
                reference["start_char"]:reference["end_char"]
            ]
