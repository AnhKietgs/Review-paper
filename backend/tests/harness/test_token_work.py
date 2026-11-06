"""Token work keeps all source spans and conservative evidence assessments."""

import json

import pytest

from app.agents.ports import LLMFailure
from app.harness.evidence import build_spans, span_source
from app.harness.token_work import combine_outputs, partition_work


def chunk(chunk_id="main-1", paper_id="main"):
    return {
        "id": chunk_id, "paper_id": paper_id, "content_version": 1,
        "text": "Nghiên cứu có 24 người. Giữ nguyên tiếng Việt 😀.\n" * 120,
        "locator": {"type": "pdf_page", "value": "7", "status": "resolved"},
    }


def context(sources):
    return {
        "scope": {"main_paper_id": "main"}, "criteria": [{"code": "method"}],
        "chunks": sources, "pending_findings": [], "reference_assessments": {},
    }


def fits(value):
    return len(json.dumps(value, ensure_ascii=False).encode()) <= 5000


def test_long_page_partitions_without_losing_or_renumbering_source_spans():
    original = chunk()
    tasks = partition_work("scientific_review", context([span_source(original)]), fits)
    assert len(tasks) > 1
    assert all(fits(task) for task in tasks)
    spans = [s for task in tasks for c in task["chunks"] for s in c["spans"]]
    assert spans == span_source(original)["spans"]
    for task in tasks:
        assert task["chunks"][0]["id"] == original["id"]
        assert task["chunks"][0]["locator"]["value"] == "7"


def test_comparison_tasks_keep_both_sides_and_cover_every_assigned_span():
    sources = [span_source(chunk()), span_source(chunk("ref-1", "ref"))]
    tasks = partition_work("related_work", context(sources), fits)
    assert all(fits(task) for task in tasks)
    for task in tasks:
        assert {c["paper_id"] for c in task["chunks"]} == {"main", "ref"}
    for source in sources:
        seen = {
            span["id"] for task in tasks for c in task["chunks"]
            if c["id"] == source["id"] for span in c["spans"]
        }
        assert seen == {s["id"] for s in source["spans"]}


def findings(count=40):
    span = build_spans(chunk()["text"])[0]
    return [{
        "id": f"f-{index}", "claim": f"Nhận xét về phương pháp {index}.",
        "kind": "analysis", "criterion_code": "method", "compared_paper_ids": [],
        "evidence": [{
            "chunk_id": "main-1", "span_id": span["id"], "quote": span["text"],
            "start_char": span["start_char"], "end_char": span["end_char"],
        }],
    } for index in range(count)]


def test_verifier_packs_small_groups_and_keeps_all_claims_and_cited_passages():
    value = context([chunk()])
    value["pending_findings"] = findings()
    tasks = partition_work("evidence_verifier", value, fits)
    assert len(tasks) > 1
    assert all(fits(task) for task in tasks)
    seen = [f["id"] for task in tasks for f in task["pending_findings"]]
    assert seen == [f["id"] for f in value["pending_findings"]]
    assert any(len(task["pending_findings"]) > 1 for task in tasks)
    for task in tasks:
        assert task["chunks"][0]["spans"][0] == span_source(chunk())["spans"][0]


def test_omission_audit_checks_every_span_for_every_topic_before_absence():
    value = context([chunk()])
    value["omission_audit"] = True
    value["pending_findings"] = [
        {**f, "kind": "omission", "evidence": []} for f in findings(3)
    ]
    tasks = partition_work("evidence_verifier", value, fits)
    for finding in value["pending_findings"]:
        seen = {
            s["id"] for task in tasks
            if finding["id"] in {f["id"] for f in task["pending_findings"]}
            for c in task["chunks"] for s in c["spans"]
        }
        assert seen == {s["id"] for s in span_source(chunk())["spans"]}
    outputs = [{"assessments": [
        {"finding_id": f["id"], "status": "unsupported", "reason": "Not here"}
        for f in task["pending_findings"]
    ]} for task in tasks]
    outputs[-1]["assessments"][0]["status"] = "supported"
    combined = combine_outputs("evidence_verifier", value, tasks, outputs)
    assert combined["assessments"][0]["status"] == "supported"
    outputs[0]["assessments"] = []
    combined = combine_outputs("evidence_verifier", value, tasks, outputs)
    assert any(a["status"] == "uncertain" for a in combined["assessments"])


def test_unsplittable_fixed_context_stops_instead_of_truncating_sources():
    value = context([span_source(chunk())])
    value["criteria"] = [{"question": "x" * 10000}]
    with pytest.raises(LLMFailure, match="token_work_item_too_large"):
        partition_work("scientific_review", value, fits)


def test_omission_topics_fit_the_largest_source_span_not_just_first_span():
    source = {
        "id": "main-1", "paper_id": "main", "content_version": 1,
        "spans": [{"id": "s0", "text": "x"}, {"id": "s1", "text": "đ" * 480}],
    }
    value = context([source])
    value["omission_audit"] = True
    value["pending_findings"] = [
        {"id": str(index), "claim": "a" * 100, "kind": "omission", "evidence": []}
        for index in range(8)
    ]
    capacity = lambda item: len(json.dumps(item, ensure_ascii=False).encode()) <= 2000
    tasks = partition_work("evidence_verifier", value, capacity)
    assert all(capacity(task) for task in tasks)
    for finding in value["pending_findings"]:
        spans = {
            span["id"] for task in tasks
            if finding["id"] in {f["id"] for f in task["pending_findings"]}
            for c in task["chunks"] for span in c["spans"]
        }
        assert spans == {"s0", "s1"}


def test_omission_windows_keep_context_across_task_boundaries_when_it_fits():
    value = context([chunk()])
    value["omission_audit"] = True
    value["pending_findings"] = [{
        "id": "topic", "claim": "sample size", "kind": "omission", "evidence": [],
    }]
    tasks = partition_work("evidence_verifier", value, fits)
    windows = [
        {s["id"] for c in task["chunks"] for s in c["spans"]} for task in tasks
    ]
    spans = span_source(chunk())["spans"]
    assert len(windows) > 1
    for left, right in zip(spans, spans[1:]):
        assert any({left["id"], right["id"]} <= window for window in windows)


def test_no_boundary_context_cannot_be_published_as_document_absence():
    value = context([{
        "id": "main-1", "paper_id": "main",
        "spans": [{"id": "s0", "text": "đ" * 480}, {"id": "s1", "text": "đ" * 480}],
    }])
    value["omission_audit"] = True
    value["pending_findings"] = [{"id": "topic", "claim": "detail", "evidence": []}]
    capacity = lambda item: len(json.dumps(item, ensure_ascii=False).encode()) <= 1800
    tasks = partition_work("evidence_verifier", value, capacity)
    assert len(tasks) == 2
    output = {"assessments": [{
        "finding_id": "topic", "status": "unsupported", "reason": "Not here",
    }]}
    combined = combine_outputs("evidence_verifier", value, tasks, [output, output])
    assert combined["assessments"][0]["status"] == "uncertain"


def test_one_claim_with_many_citations_splits_evidence_without_losing_sources():
    value = context([chunk()])
    finding = findings(1)[0]
    finding["evidence"] = [{
        **finding["evidence"][0], "span_id": span["id"], "quote": span["text"],
        "start_char": span["start_char"], "end_char": span["end_char"],
    } for span in build_spans(chunk()["text"])]
    value["pending_findings"] = [finding]
    tasks = partition_work("evidence_verifier", value, fits)
    assert len(tasks) > 1
    assert all(fits(task) for task in tasks)
    seen = {
        e["span_id"] for task in tasks
        for f in task["pending_findings"] for e in f["evidence"]
    }
    assert seen == {s["id"] for s in build_spans(chunk()["text"])}
    outputs = [{"assessments": [{
        "finding_id": finding["id"], "status": "supported", "reason": "Supports",
    }]} for _ in tasks]
    assert combine_outputs("evidence_verifier", value, tasks, outputs)["assessments"][0]["status"] == "supported"
    outputs[-1]["assessments"][0]["status"] = "unsupported"
    assert combine_outputs("evidence_verifier", value, tasks, outputs)["assessments"][0]["status"] == "uncertain"


def test_split_comparison_evidence_keeps_both_papers_in_every_assessment():
    value = context([chunk(), chunk("ref-1", "ref")])
    finding = findings(1)[0]
    finding.update(kind="comparison", compared_paper_ids=["ref"])
    finding["evidence"] = [{
        **finding["evidence"][0], "chunk_id": source["id"],
        "span_id": span["id"], "quote": span["text"],
        "start_char": span["start_char"], "end_char": span["end_char"],
    } for source in value["chunks"] for span in build_spans(source["text"])[:5]]
    value["pending_findings"] = [finding]
    capacity = lambda item: len(json.dumps(item, ensure_ascii=False).encode()) <= 8000
    tasks = partition_work("evidence_verifier", value, capacity)
    assert len(tasks) > 1
    for task in tasks:
        assert capacity(task)
        assert {c["paper_id"] for c in task["chunks"]} == {"main", "ref"}
    seen = {
        (e["chunk_id"], e["span_id"]) for task in tasks
        for f in task["pending_findings"] for e in f["evidence"]
    }
    assert seen == {(e["chunk_id"], e["span_id"]) for e in finding["evidence"]}
