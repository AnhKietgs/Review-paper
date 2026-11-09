"""Synthetic request-budget benchmark, not a Groq billing/quality evaluation."""

from app.agents.graph_factory import AgentFactory
from app.harness.evidence import build_spans, span_source
from app.harness.token_work import partition_work
from app.infrastructure.groq.client import GroqClient
from app.infrastructure.groq.quota import GroqQuota, estimate_input_tokens


def benchmark():
    criteria = [{"code": f"c{i}", "question": f"Assess criterion {i}",
                 "guidance": "Check original evidence and scope."} for i in range(4)]
    chunks, notes = [], []
    for index in range(9):
        text = (f"Nghiên cứu {index} khảo sát 24 người bằng bảng hỏi. "
                "Kết quả chỉ phản ánh mẫu khảo sát, chưa chứng minh quan hệ nhân quả. ") * 30
        chunk = {"id": f"page-{index}", "paper_id": "main", "content_version": 1,
                 "text": text, "locator": {"type": "pdf_page", "value": str(index + 1),
                                          "status": "resolved"}}
        chunks.append(span_source(chunk))
        span = build_spans(text)[0]
        notes.append({"id": f"note-{index}", "criterion_code": f"c{index % 4}",
                      "text": f"Nghiên cứu {index} dùng bảng hỏi, mẫu 24 người.",
                      "evidence": [{"chunk_id": chunk["id"], "span_id": span["id"],
                                    "quote": span["text"]}]})
    common = {"scope": {"main_paper_id": "main"}, "criteria": criteria,
              "pending_findings": [], "reference_assessments": {}}

    def measure(contexts, output_limit):
        client = GroqClient("offline", "model", completion=lambda **_: None,
                            max_completion_tokens=output_limit, quota=GroqQuota())
        count, inputs = 0, 0
        for context in contexts:
            tasks = partition_work("scientific_review", context, lambda task:
                client.fits_request(*AgentFactory.request("scientific_review", client, task)))
            for task in tasks:
                messages, schema = AgentFactory.request("scientific_review", client, task)
                tokens = estimate_input_tokens(client.schema_request(messages, schema))
                assert tokens + output_limit <= 8000
                count += 1
                inputs += tokens
        return {"tasks": count, "input": inputs, "reserved": inputs + count * output_limit}

    baseline = measure([{**common, "chunks": [c]} for c in chunks], 3072)
    reading = measure([{**common, "chunks": [c], "scientific_phase": "extract"}
                       for c in chunks], 1536)
    synthesis = measure([{**common, "chunks": chunks, "notes": notes,
                          "scientific_phase": "synthesize"}], 2048)
    return baseline, reading, synthesis


def test_two_phase_scientific_request_reservations_are_lower_on_fixed_corpus():
    baseline, reading, synthesis = benchmark()
    assert reading["reserved"] + synthesis["reserved"] < baseline["reserved"]
    assert synthesis["tasks"] < baseline["tasks"]
