"""Token-sized runtime work over immutable source span identities."""

import re

from app.agents.ports import LLMFailure
from app.harness.evidence import build_spans, span_source


def _source(chunk):
    return chunk if "spans" in chunk else span_source(chunk)


def _with_atoms(context, atoms):
    chunks = {}
    seen = set()
    for source, span in atoms:
        key = (source["id"], span["id"])
        if key in seen:
            continue
        seen.add(key)
        if source["id"] not in chunks:
            chunks[source["id"]] = {**source, "spans": []}
        chunks[source["id"]]["spans"].append(span)
    return {**context, "chunks": list(chunks.values())}


def _pack_sources(context, fits, paired=False, overlap=False):
    atoms = [
        (source, span) for chunk in context["chunks"]
        for source in [_source(chunk)] for span in source["spans"]
    ]
    anchors = {}
    if paired:
        for atom in atoms:
            anchors.setdefault(atom[0]["paper_id"], atom)
    tasks, current = [], []
    for atom in atoms:
        candidate = current + [atom]
        present = {source["paper_id"] for source, _ in candidate}
        candidate += [
            anchor for paper, anchor in anchors.items() if paper not in present
        ]
        if fits(_with_atoms(context, candidate)):
            current = candidate
            continue
        previous = current[-1] if current else None
        if current:
            tasks.append(_with_atoms(context, current))
        current = [atom]
        current += [
            anchor for paper, anchor in anchors.items() if paper != atom[0]["paper_id"]
        ]
        if overlap and previous and fits(_with_atoms(context, [previous] + current)):
            current.insert(0, previous)
        if not fits(_with_atoms(context, current)):
            raise LLMFailure("token_work_item_too_large")
    if current:
        tasks.append(_with_atoms(context, current))
    if not tasks:
        if not fits(context):
            raise LLMFailure("token_work_item_too_large")
        return [context]
    return tasks


def _cited_context(context, findings, neighbors=True):
    sources = {chunk["id"]: chunk for chunk in context["chunks"]}
    selected = {}
    for finding in findings:
        for reference in finding["evidence"]:
            source = sources[reference["chunk_id"]]
            spans = _source(source)["spans"]
            wanted = selected.setdefault(source["id"], set())
            indexes = []
            if reference.get("span_id") is not None:
                indexes = [
                    index for index, span in enumerate(spans)
                    if span["id"] == reference["span_id"]
                ]
            elif "text" in source:
                pattern = r"\s+".join(
                    re.escape(part) for part in reference["quote"].split()
                )
                match = re.search(pattern, source["text"])
                if match:
                    indexes = [
                        index for index, span in enumerate(build_spans(source["text"]))
                        if span["start_char"] < match.end()
                        and span["end_char"] > match.start()
                    ]
            if not indexes:
                # Never pretend omitted evidence was inspected.
                raise LLMFailure("source_span_not_found")
            for index in indexes:
                wanted.add(index)
                if neighbors:
                    wanted.update(
                        i for i in (index - 1, index + 1) if 0 <= i < len(spans)
                    )
    atoms = [
        (_source(source), span)
        for chunk_id, indexes in selected.items() for source in [sources[chunk_id]]
        for index, span in enumerate(_source(source)["spans"]) if index in indexes
    ]
    return _with_atoms({**context, "pending_findings": findings}, atoms)


def _evidence_tasks(context, finding, fits):
    """A long evidence union can be judged in complete, source-safe subsets."""
    sources = {source["id"]: source for source in context["chunks"]}
    anchors = {}
    if finding["kind"] == "comparison":
        for reference in finding["evidence"]:
            anchors.setdefault(sources[reference["chunk_id"]]["paper_id"], reference)

    def task(references):
        unique = []
        for reference in references:
            if reference not in unique:
                unique.append(reference)
        partial = {**finding, "evidence": unique}
        return _cited_context(context, [partial], neighbors=False)

    tasks, current = [], []
    for reference in finding["evidence"]:
        candidate = current + [reference]
        present = {sources[item["chunk_id"]]["paper_id"] for item in candidate}
        candidate += [
            anchor for paper, anchor in anchors.items() if paper not in present
        ]
        if fits(task(candidate)):
            current = candidate
            continue
        if current:
            tasks.append(task(current))
        paper = sources[reference["chunk_id"]]["paper_id"]
        current = [reference] + [a for p, a in anchors.items() if p != paper]
        if not fits(task(current)):
            raise LLMFailure("token_work_item_too_large")
    if current:
        tasks.append(task(current))
    return tasks


def _verification_tasks(context, fits):
    tasks, current = [], []
    for finding in context["pending_findings"]:
        candidate = _cited_context(context, current + [finding])
        if fits(candidate):
            current.append(finding)
            continue
        if current:
            tasks.append(_cited_context(context, current))
        current = [finding]
        candidate = _cited_context(context, current)
        if not fits(candidate):
            candidate = _cited_context(context, current, neighbors=False)
            if not fits(candidate):
                tasks.extend(_evidence_tasks(context, finding, fits))
            else:
                tasks.append(candidate)
            current = []
    if current:
        tasks.append(_cited_context(context, current))
    return tasks


def _omission_tasks(context, fits):
    atoms = [
        (source, span) for chunk in context["chunks"]
        for source in [_source(chunk)] for span in source["spans"]
    ]
    groups, current = [], []
    for finding in context["pending_findings"]:
        candidate = {**context, "pending_findings": current + [finding]}
        if current and not all(
            fits(_with_atoms(candidate, [atom])) for atom in atoms
        ):
            groups.append(current)
            current = []
        current.append(finding)
    if current:
        groups.append(current)
    return [
        task for group in groups for task in _pack_sources(
            {**context, "pending_findings": group}, fits, overlap=True,
        )
    ]


def partition_work(role: str, context: dict, fits) -> list[dict]:
    """Pack complete requests; never renumber source IDs or discard assigned text."""
    context = {**context, "reference_assessments": {}}
    if role == "evidence_verifier":
        if context.get("omission_audit"):
            return _omission_tasks(context, fits)
        return _verification_tasks(context, fits)
    context["pending_findings"] = []
    if fits(context):
        return [context]
    return _pack_sources(context, fits, paired=role == "related_work")


def _has_boundary_context(context, tasks, finding_id):
    atoms = [
        (chunk["id"], span["id"]) for chunk in context["chunks"]
        for span in _source(chunk)["spans"]
    ]
    missing = set(zip(atoms, atoms[1:]))
    for task in tasks:
        if finding_id not in {item["id"] for item in task["pending_findings"]}:
            continue
        window = {
            (chunk["id"], span["id"]) for chunk in task["chunks"]
            for span in _source(chunk)["spans"]
        }
        missing = {pair for pair in missing if not set(pair) <= window}
    return not missing


def _combine_assessments(context, tasks, outputs):
    collected = {}
    for task, output in zip(tasks, outputs):
        assessments = {item["finding_id"]: item for item in output["assessments"]}
        for finding in task["pending_findings"]:
            item = assessments.get(finding["id"], {
                "finding_id": finding["id"], "status": "uncertain",
                "reason": "Verifier omitted this work item",
            })
            collected.setdefault(finding["id"], []).append(item)
    result = []
    for finding_id, items in collected.items():
        if not context.get("omission_audit"):
            statuses = {item["status"] for item in items}
            result.append(items[0] if len(statuses) == 1 else {
                "finding_id": finding_id, "status": "uncertain",
                "reason": "Các nhóm bằng chứng chưa thống nhất; "
                "chưa đủ căn cứ xác nhận toàn bộ nhận xét.",
            })
            continue
        statuses = {item["status"] for item in items}
        status = (
            "supported" if "supported" in statuses else
            "uncertain" if "uncertain" in statuses else "unsupported"
        )
        if status == "unsupported" and not _has_boundary_context(
            context, tasks, finding_id,
        ):
            result.append({
                "finding_id": finding_id, "status": "uncertain",
                "reason": "Ngân sách không đủ giữ ngữ cảnh qua ranh giới các phần; "
                "chưa thể kết luận thông tin vắng mặt.",
            })
            continue
        reason = next(item["reason"] for item in items if item["status"] == status)
        result.append({"finding_id": finding_id, "status": status, "reason": reason})
    return {"assessments": result}


def combine_outputs(role: str, context: dict, tasks: list, outputs: list) -> dict:
    """Publish only after all work finishes; absence needs every source window."""
    if role == "evidence_verifier":
        return _combine_assessments(context, tasks, outputs)
    findings = [finding for output in outputs for finding in output["findings"]]
    if role == "related_work":
        return {
            "findings": findings,
            "assessment": "assessed" if any(
                output["assessment"] == "assessed" for output in outputs
            ) else "not_assessed",
            "reason": " | ".join(dict.fromkeys(output["reason"] for output in outputs)),
        }
    analysis = {}
    for output in outputs:
        for key, value in output["analysis"].items():
            analysis.setdefault(key, []).append(value)
    return {
        "findings": findings,
        "analysis": {key: "\n".join(values) for key, values in analysis.items()},
    }
