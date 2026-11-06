"""Bounded loop owned by the harness, with one worker per turn."""

import re
from copy import deepcopy
from uuid import uuid4

from app.agents.graph_factory import AgentFactory
from app.agents.ports import LLMFailure, RateLimitPause
from app.agents.schemas import AgentAction, FindingDraft
from app.agents.supervisor import Supervisor, eligible_actions
from app.harness.context import ContextBuilder
from app.harness.document_queue import DocumentQueue
from app.harness.events import RunEventInput, RunEventRecorder
from app.harness.evidence import EvidenceResolutionError, EvidenceResolver
from app.harness.finding_merge import finding_key, merge_evidence
from app.harness.memory import RunMemory
from app.harness.output_gate import OutputGate
from app.harness.state import RunState, TurnProgress
from app.harness.tool_gateway import ToolCall, ToolGateway
from app.harness.turn_checkpoint import (
    reusable_context, save_progress, turn_budget_exhausted,
)


class AgentRunner:
    """Host four logical agents with deterministic control boundaries."""

    def __init__(self, llm, catalog, memory: RunMemory, events: RunEventRecorder):
        self.llm = llm
        self.catalog = catalog
        self.memory = memory
        self.events = events
        self.graphs = {}
        self.context_builder = ContextBuilder()
        self.output_gate = OutputGate(catalog)
        self.evidence_resolver = EvidenceResolver(catalog)

    def _event(
        self, state: RunState, agent: str, action: str, summary: str = "", **payload
    ) -> None:
        self.events.append(
            state.run_id,
            RunEventInput(
                agent=agent,
                action=action,
                output_summary=summary,
                payload={"turn": state.turn_count, **payload},
            ),
        )

    def _client(self, role: str):
        return self.llm.for_role(role) if hasattr(self.llm, "for_role") else self.llm

    def _graph(self, role: str):
        if role not in self.graphs:
            self.graphs[role] = AgentFactory.build(role, self._client(role))
        return self.graphs[role]

    def _selects_evidence(self, role: str) -> bool:
        return role in {"scientific_review", "related_work"} and getattr(
            self._client(role), "evidence_selection_mode", False
        )

    def _model_id(self, role: str) -> str:
        """Expose only the selected model ID, never provider credentials."""
        if hasattr(self.llm, "model_for"):
            return self.llm.model_for(role)
        return "fixture" if self.llm.__class__.__name__ == "FixtureClient" else "custom"

    def _invoke(self, state: RunState, role: str, context: dict) -> dict:
        progress = state.turn_progress
        if progress is not None:
            if (
                progress.output is not None and progress.context_role == role
                and progress.context == context
            ):
                self._event(state, role, "worker_output_reused")
                return deepcopy(progress.output)
            progress.context = deepcopy(context)
            progress.context_role = role
            progress.output = None
        self._event(state, role, "agent_started", model=self._model_id(role))
        state.call_counts[role] = state.call_counts.get(role, 0) + 1
        save_progress(self.memory, state)
        output = self._graph(role).invoke({"context": context})["output"]
        self._event(state, role, "agent_finished", "Structured output received")
        if self._selects_evidence(role):
            self._resolve_evidence(state, role, output, context["chunks"])
        if progress is not None:
            progress.output = deepcopy(output)
            save_progress(self.memory, state)
        return output

    def _resolve_evidence(self, state, role, output, sources) -> None:
        """Materialize authoritative evidence before normal staging or repairs."""
        for index, finding in enumerate(output["findings"]):
            try:
                finding["evidence"] = self.evidence_resolver.resolve(
                    finding["evidence"], state.scope, sources,
                )
            except EvidenceResolutionError as exc:
                finding["evidence"] = []
                self._event(
                    state, role, "evidence_resolution_failed", str(exc),
                    finding_index=index,
                )
                continue
            self._event(
                state, role, "evidence_resolved", "Exact text loaded from source spans",
                finding_index=index,
                positions=[
                    {key: reference[key] for key in (
                        "chunk_id", "span_id", "start_char", "end_char",
                    )}
                    for reference in finding["evidence"]
                ],
            )

    def _queue_repair(
        self, state: RunState, finding: dict, role: str, source_ids: list[str]
    ) -> None:
        if finding["id"] in state.repair_attempted_ids:
            return
        if state.repair_count + len(state.repair_queue) >= state.max_repairs:
            self._event(
                state, "harness", "repair_skipped", "Repair budget exhausted",
                finding_id=finding["id"],
            )
            return
        state.repair_attempted_ids.append(finding["id"])
        state.repair_queue.append(
            {
                "finding_id": finding["id"], "role": role,
                "source_ids": list(dict.fromkeys(source_ids)),
            }
        )
        self._event(
            state, "harness", "repair_queued", "One bounded repair attempt",
            finding_id=finding["id"], role=role,
        )

    def _stage(
        self, state: RunState, drafts: list[dict], role: str, source_ids: list[str]
    ) -> None:
        for draft in drafts:
            finding = FindingDraft.model_validate(draft).model_dump(mode="json")
            # Model-generated IDs must never address an existing persisted finding.
            finding["id"] = str(uuid4())
            if finding["kind"] == "limitation":
                omission = re.match(
                    r"^(?:bài báo|nghiên cứu)\s+(?:không|chưa)\s+"
                    r"(?:cung cấp|nêu|báo cáo|trình bày|mô tả|"
                    r"đề cập(?:\s+(?:đến|tới))?)\s+(.+)$",
                    finding["claim"].strip(), re.IGNORECASE,
                )
                if omission:
                    finding["kind"] = "omission"
                    finding["claim"] = omission.group(1).rstrip(". ")
            if finding["kind"] == "omission":
                finding["evidence"] = []
                if not self._merge_duplicate(state, finding):
                    state.omission_audits.append(
                        {"finding": finding, "checked": 0, "ambiguous": False}
                    )
                    self._event(
                        state, "harness", "omission_deferred",
                        "Waiting for full main-paper coverage",
                        finding_id=finding["id"], topic=finding["claim"],
                    )
                continue
            if self._merge_duplicate(state, finding):
                continue
            result = self.output_gate.validate(finding, state.scope)
            self._event(
                state,
                "output_gate",
                "validation_passed" if result.passed else "validation_failed",
                ", ".join(result.reason_codes),
                finding_id=finding["id"],
                checks=result.checks,
            )
            if result.passed:
                state.pending_findings.append(finding)
            else:
                sources, _ = merge_evidence(
                    {**finding, "evidence": []}, finding,
                    self.output_gate, state.scope,
                )
                state.findings.append(
                    {
                        **finding,
                        "evidence": sources,
                        "status": "unsupported",
                        "verdict": ", ".join(result.reason_codes),
                    }
                )
                self._queue_repair(state, finding, role, source_ids)

    def _merge_duplicate(self, state: RunState, finding: dict) -> bool:
        """Retain a canonical claim and reopen it only for new valid evidence."""
        candidates = (
            state.pending_findings + state.findings
            + [item["finding"] for item in state.omission_audits]
        )
        existing = next((
            item for item in candidates if finding_key(item) == finding_key(finding)
        ), None)
        if existing is None:
            return False
        sources, added = merge_evidence(
            existing, finding, self.output_gate, state.scope,
        )
        reopened = False
        if added or sources != existing["evidence"]:
            candidate = {
                key: value for key, value in existing.items()
                if key not in {"status", "verdict"}
            }
            candidate["evidence"] = sources
            if self.output_gate.validate(candidate, state.scope).passed:
                state.findings = [
                    item for item in state.findings if item["id"] != existing["id"]
                ]
                if existing in state.pending_findings:
                    index = state.pending_findings.index(existing)
                    state.pending_findings[index] = candidate
                else:
                    state.pending_findings.append(candidate)
                reopened = True
            else:
                # A comparison can collect each side in separate drafts. Keep
                # valid partial sources, but never send it past the full gate.
                existing["evidence"] = sources
        self._merge_repair_jobs(state, existing["id"], finding["id"], reopened)
        for job in state.repair_queue:
            if job["finding_id"] == existing["id"]:
                job["source_ids"] = list(dict.fromkeys(
                    job["source_ids"] + [item["chunk_id"] for item in sources]
                ))
        self._event(
            state, "harness", "findings_merged",
            "Duplicate claim consolidated before verification",
            canonical_finding_id=existing["id"], merged_finding_id=finding["id"],
            added_evidence=added, verification_reopened=reopened,
            verification_pending=any(
                item["id"] == existing["id"] for item in state.pending_findings
            ),
        )
        return True

    @staticmethod
    def _merge_repair_jobs(state, canonical_id, duplicate_id, reopened):
        """Keep at most one bounded repair job and carry attempted identity."""
        ids = {canonical_id, duplicate_id}
        jobs = [job for job in state.repair_queue if job["finding_id"] in ids]
        queued_ids = {job["finding_id"] for job in jobs}
        already_repaired = any(
            item in state.repair_attempted_ids for item in ids - queued_ids
        )
        state.repair_queue = [
            job for job in state.repair_queue if job["finding_id"] not in ids
        ]
        if jobs and not reopened:
            state.repair_queue.append({
                **jobs[0], "finding_id": canonical_id,
                "source_ids": list(dict.fromkeys(
                    source for job in jobs for source in job["source_ids"]
                )),
            })
        if reopened and jobs and not already_repaired:
            # Queueing reserves the attempt before execution. Evidence can
            # recover first, so cancelling that job must release its reservation.
            state.repair_attempted_ids = [
                item for item in state.repair_attempted_ids if item not in ids
            ]
        elif any(item in state.repair_attempted_ids for item in ids):
            state.repair_attempted_ids = list(dict.fromkeys(
                canonical_id if item in ids else item
                for item in state.repair_attempted_ids
            ))

    def _consolidate_pending(self, state: RunState) -> None:
        """Normalize restored or repaired queues without allocating new IDs."""
        pending = state.pending_findings
        state.pending_findings = []
        for finding in pending:
            if not self._merge_duplicate(state, finding):
                state.pending_findings.append(finding)

    def _context(
        self,
        state: RunState,
        gateway: ToolGateway,
        role: str,
        ids: list[str],
        extra: list[dict] | None = None,
    ) -> dict:
        source_ids = list(dict.fromkeys(
            ids + [item["id"] for item in (extra or [])]
        ))
        cached = reusable_context(state, role, source_ids, self.catalog)
        if cached is not None:
            self._event(state, "context", "context_reused", f"Context for {role}")
            return cached
        if state.turn_progress is not None:
            state.turn_progress.context = None
            state.turn_progress.output = None
        result = gateway.execute(
            ToolCall(
                agent=role, name="read_chunks", arguments={"chunk_ids": source_ids},
            ),
            state.scope,
        )
        if not result.allowed:
            raise ValueError("Source permission denied")
        rubric = gateway.execute(
            ToolCall(agent="supervisor", name="read_rubric"), state.scope
        )
        context = self.context_builder.build(
            state, result.data, rubric.data,
            include_spans=self._selects_evidence(role),
        )
        self._event(
            state,
            "context",
            "context_built",
            f"Context for {role}",
            source_ids=[item["id"] for item in context["chunks"]],
        )
        if state.turn_progress is not None:
            state.turn_progress.context_role = role
            state.turn_progress.source_ids = source_ids
            state.turn_progress.context = deepcopy(context)
            save_progress(self.memory, state)
        return context

    def _analyze(self, state: RunState, gateway: ToolGateway) -> None:
        context = self._context(
            state, gateway, "scientific_review", state.current_batch_ids
        )
        output = self._invoke(state, "scientific_review", context)
        for key, value in output["analysis"].items():
            state.analysis.setdefault(key, []).append(value)
        self._stage(
            state, output["findings"], "scientific_review", state.current_batch_ids
        )
        state.processed_chunk_ids.extend(state.current_batch_ids)
        state.remaining_chunk_ids = [
            item
            for item in state.remaining_chunk_ids
            if item not in state.current_batch_ids
        ]
        state.current_batch_ids = []

    def _compare(self, state: RunState, gateway: ToolGateway, paper_id: str) -> None:
        progress = state.comparison_progress.get(paper_id)
        if progress is not None:
            self._compare_batch(state, gateway, paper_id, progress)
            return
        query = " ".join(item["claim"] for item in state.findings[:3])
        sources = gateway.execute(
            ToolCall(
                agent="related_work",
                name="search_reference",
                arguments={"paper_id": paper_id, "query": query},
            ),
            state.scope,
        )
        if not sources.allowed or not sources.data or not state.processed_chunk_ids:
            state.reference_assessments[paper_id] = {
                "status": "not_assessed",
                "reason": sources.reason or "No readable sources",
                "chunk_ids": [],
            }
            self._event(state, "related_work", "agent_skipped", "Reference unavailable")
            return
        if state.llm_mode == "groq":
            main_ids = state.processed_chunk_ids[:2]
            reference_ids = [item["id"] for item in sources.data]
            progress = {
                "groups": [
                    [main_ids[index % len(main_ids)],
                     reference_ids[index % len(reference_ids)]]
                    for index in range(max(len(main_ids), len(reference_ids)))
                ],
                "cursor": 0,
                "assessments": [],
                "chunk_ids": reference_ids,
            }
            state.comparison_progress[paper_id] = progress
            self._compare_batch(state, gateway, paper_id, progress)
            return
        context = self._context(
            state, gateway, "related_work", state.processed_chunk_ids[:2], sources.data
        )
        output = self._invoke(state, "related_work", context)
        state.reference_assessments[paper_id] = {
            "status": output["assessment"],
            "reason": output["reason"],
            "chunk_ids": [item["id"] for item in sources.data],
        }
        self._stage(
            state, output["findings"], "related_work",
            [item["id"] for item in context["chunks"]],
        )

    def _compare_batch(self, state, gateway, paper_id, progress) -> None:
        """Compare one source pair, checkpointing all selected pairs across turns."""
        if not self.catalog.is_active(paper_id):
            state.reference_assessments[paper_id] = {
                "status": "not_assessed",
                "reason": "Reference became unavailable between comparison batches",
                "chunk_ids": [],
            }
            del state.comparison_progress[paper_id]
            self._event(
                state, "related_work", "agent_skipped", "Reference unavailable"
            )
            return
        ids = progress["groups"][progress["cursor"]]
        context = self._context(state, gateway, "related_work", ids)
        output = self._invoke(state, "related_work", context)
        self._stage(state, output["findings"], "related_work", ids)
        progress["cursor"] += 1
        progress["assessments"].append({
            "status": output["assessment"], "reason": output["reason"],
        })
        self._event(
            state, "related_work", "comparison_batch_completed",
            "Compared one bounded main/reference source pair",
            paper_id=paper_id, completed=progress["cursor"],
            total=len(progress["groups"]), source_ids=ids,
        )
        if progress["cursor"] == len(progress["groups"]):
            assessed = any(
                item["status"] == "assessed" for item in progress["assessments"]
            )
            state.reference_assessments[paper_id] = {
                "status": "assessed" if assessed else "not_assessed",
                "reason": " | ".join(
                    item["reason"] for item in progress["assessments"]
                ),
                "chunk_ids": progress["chunk_ids"],
                "batches": progress["assessments"],
            }
            del state.comparison_progress[paper_id]

    def _verify(self, state: RunState, gateway: ToolGateway) -> None:
        self._consolidate_pending(state)
        valid = []
        for finding in state.pending_findings:
            result = self.output_gate.validate(finding, state.scope)
            if result.passed:
                valid.append(finding)
            else:
                state.findings.append(
                    {
                        **finding,
                        "evidence": [],
                        "status": "unsupported",
                        "verdict": ", ".join(result.reason_codes),
                    }
                )
                self._queue_repair(
                    state, finding, "related_work" if finding["kind"] == "comparison"
                    else "scientific_review",
                    [item["chunk_id"] for item in finding["evidence"]],
                )
                self._event(
                    state,
                    "output_gate",
                    "validation_failed",
                    ", ".join(result.reason_codes),
                    finding_id=finding["id"],
                )
        state.pending_findings = valid
        if not valid:
            self._event(
                state,
                "evidence_verifier",
                "agent_skipped",
                "No findings passed provenance validation",
            )
            return
        ids = list(
            dict.fromkeys(
                item["chunk_id"]
                for finding in state.pending_findings
                for item in finding["evidence"]
            )
        )
        context = self._context(state, gateway, "evidence_verifier", ids)
        output = self._invoke(state, "evidence_verifier", context)
        assessments = {item["finding_id"]: item for item in output["assessments"]}
        for finding in state.pending_findings:
            result = self.output_gate.validate(finding, state.scope)
            assessment = assessments.get(
                finding["id"],
                {
                    "status": "uncertain",
                    "reason": "Verifier omitted this finding",
                },
            )
            status = assessment["status"] if result.passed else "unsupported"
            if finding["kind"] == "question" and status == "supported":
                status = "grounded"
            state.findings.append(
                {
                    **finding,
                    "evidence": finding["evidence"] if result.passed else [],
                    "status": status,
                    "verdict": assessment["reason"],
                }
            )
            if status not in {"supported", "grounded"}:
                self._queue_repair(
                    state, finding,
                    "related_work" if finding["kind"] == "comparison"
                    else "scientific_review",
                    [item["chunk_id"] for item in finding["evidence"]],
                )
            self._event(
                state,
                "output_gate",
                "finding_verified",
                status,
                finding_id=finding["id"],
                checks=result.checks,
            )
        state.pending_findings = []

    def _repair(self, state: RunState, gateway: ToolGateway) -> None:
        request = state.repair_queue.pop(0)
        state.repair_count += 1
        original = next(
            (item for item in state.findings if item["id"] == request["finding_id"]),
            None,
        )
        if original is None:
            return
        role = request["role"]
        ids = [
            chunk_id for chunk_id in request["source_ids"]
            if self.catalog.chunk(chunk_id) is not None
            and state.scope.permits(
                self.catalog.chunk(chunk_id)["paper_id"],
                self.catalog.chunk(chunk_id)["content_version"],
            )
        ]
        if not ids:
            ids = state.processed_chunk_ids[-2:]
        if not ids:
            self._event(state, role, "repair_skipped", "No allowed source chunks")
            return
        context = self._context(state, gateway, role, ids)
        context["repair_request"] = {
            "claim": original["claim"],
            "kind": original["kind"],
            "verdict": original["verdict"],
        }
        output = self._invoke(state, role, context)
        candidates = [
            FindingDraft.model_validate(item).model_dump(mode="json")
            for item in output["findings"]
            if item["kind"] == original["kind"]
            and item["criterion_code"] == original["criterion_code"]
            and all(source["chunk_id"] in ids for source in item["evidence"])
        ]
        if not candidates:
            self._event(state, role, "repair_unresolved", "No supported revision")
            return
        candidate = candidates[0]
        candidate["id"] = original["id"]
        result = self.output_gate.validate(candidate, state.scope)
        self._event(
            state, "output_gate",
            "validation_passed" if result.passed else "validation_failed",
            ", ".join(result.reason_codes), finding_id=candidate["id"],
            checks=result.checks,
        )
        if not result.passed:
            self._event(state, role, "repair_unresolved", "Provenance still invalid")
            return
        state.findings = [
            item for item in state.findings if item["id"] != original["id"]
        ]
        if candidate["id"] not in state.repair_attempted_ids:
            state.repair_attempted_ids.append(candidate["id"])
        if not self._merge_duplicate(state, candidate):
            state.pending_findings.append(candidate)
        self._event(
            state, role, "finding_repaired", "Revision sent to Evidence Verifier",
            original_finding_id=original["id"], finding_id=candidate["id"],
        )

    def _finish_omission(self, state: RunState, audit: dict) -> None:
        """Publish only a scoped result after the complete source scan."""
        finding = audit["finding"]
        status = "uncertain" if audit["ambiguous"] else "not_reported"
        topic = finding["claim"]
        if audit["ambiguous"]:
            finding["claim"] = (
                f"Chưa thể kết luận về {topic} trong văn bản trích xuất "
                f"v{state.scope.main_version} sau khi rà soát "
                f"{audit['checked']} đoạn."
            )
        else:
            finding["claim"] = (
                f"Không tìm thấy thông tin về {topic} trong văn bản trích xuất "
                f"v{state.scope.main_version} sau khi rà soát "
                f"{audit['checked']} đoạn."
            )
        finding["status"] = status
        finding["verdict"] = (
            "Một hoặc nhiều đoạn không đủ rõ để kết luận."
            if audit["ambiguous"]
            else "Đã rà soát toàn bộ văn bản trích xuất; "
            "đây là giới hạn báo cáo thông tin, không chứng minh sự vắng mặt "
            "ở các nguồn khác."
        )
        state.findings.append(finding)
        self._event(
            state, "harness", "omission_completed", status,
            finding_id=finding["id"], checked=audit["checked"],
        )

    def _audit_omission(self, state: RunState, gateway: ToolGateway) -> None:
        """Audit several omission topics against one bounded source group."""
        if state.remaining_chunk_ids or state.current_batch_ids:
            raise ValueError("Omission audit requires full document coverage")
        cursor = state.omission_audits[0]["checked"]
        audits = [
            item for item in state.omission_audits
            if item["checked"] == cursor
        ][:10]
        ids = state.processed_chunk_ids[cursor:cursor + 2]
        if not ids:
            for audit in audits:
                state.omission_audits.remove(audit)
                self._event(
                    state, "harness", "omission_unresolved",
                    "No main-paper chunks available for audit",
                    finding_id=audit["finding"]["id"],
                )
            return
        context = self._context(state, gateway, "evidence_verifier", ids)
        context["pending_findings"] = [item["finding"] for item in audits]
        context["omission_audit"] = True
        try:
            output = self._invoke(state, "evidence_verifier", context)
        except RateLimitPause:
            # Provider throttling must suspend the run, not turn an unfinished
            # whole-paper audit into an uncertain finding.
            raise
        except LLMFailure as exc:
            if str(exc) not in {"invalid_model_output", "rate_limited"}:
                raise
            for audit in audits:
                state.omission_audits.remove(audit)
                finding = audit["finding"]
                finding["claim"] = (
                    f"Chưa thể kết luận về {finding['claim']} trong văn bản "
                    f"trích xuất v{state.scope.main_version}."
                )
                finding["status"] = "uncertain"
                finding["verdict"] = (
                    "Lượt kiểm tra toàn bài chưa hoàn tất do lỗi đầu ra "
                    f"Evidence Verifier: {exc}."
                )
                state.findings.append(finding)
                self._event(
                    state, "evidence_verifier", "omission_audit_unavailable",
                    str(exc), finding_id=finding["id"], source_ids=ids,
                )
            return
        assessments = {
            item["finding_id"]: item for item in output["assessments"]
        }
        for audit in audits:
            finding = audit["finding"]
            assessment = assessments.get(
                finding["id"],
                {"status": "uncertain", "reason": "Verifier omitted audit result"},
            )
            audit["checked"] += len(ids)
            self._event(
                state, "evidence_verifier", "omission_audited",
                assessment["reason"], finding_id=finding["id"],
                source_ids=ids, result=assessment["status"],
            )
            if assessment["status"] == "supported":
                state.omission_audits.remove(audit)
                self._event(
                    state, "harness", "omission_refuted",
                    "The detail was found in the extracted paper",
                    finding_id=finding["id"], source_ids=ids,
                )
                continue
            if assessment["status"] == "uncertain":
                audit["ambiguous"] = True
            if audit["checked"] == len(state.processed_chunk_ids):
                state.omission_audits.remove(audit)
                self._finish_omission(state, audit)

    def _supervisor_action(self, state: RunState) -> AgentAction:
        """Use the sole legal action when model output cannot be parsed."""
        self._event(
            state, "supervisor", "agent_started", model=self._model_id("supervisor")
        )
        state.call_counts["supervisor"] = state.call_counts.get("supervisor", 0) + 1
        try:
            action = Supervisor(self._graph("supervisor")).decide(state)
        except RateLimitPause:
            # A quota error is retryable and must preserve this turn's checkpoint.
            # It is not equivalent to malformed supervisor output.
            raise
        except LLMFailure as exc:
            if str(exc) not in {"invalid_model_output", "rate_limited"}:
                raise
            selected = eligible_actions(state)
            if len(selected) != 1:
                raise
            reference_id = None
            if selected[0] == "compare":
                reference_id = sorted(
                    set(state.scope.reference_versions)
                    - set(state.reference_assessments)
                )[0]
            action = AgentAction(
                action=selected[0],
                reason="Chọn hành động hợp lệ duy nhất sau lỗi đầu ra Supervisor",
                reference_paper_id=reference_id,
            )
            self._event(
                state, "supervisor", "supervisor_fallback",
                str(exc), selected_action=action.action,
            )
        self._event(
            state,
            "supervisor",
            "decision",
            action.reason,
            selected_action=action.action,
        )
        return action

    def _turn_action(self, state: RunState) -> AgentAction:
        """Persist a fresh decision or resume the already admitted turn."""
        if state.turn_progress is None:
            state.turn_count += 1
        if not state.initialized:
            state.initialized = True
            if not state.scope.reference_versions:
                self._event(
                    state, "related_work", "agent_skipped", "No selected references"
                )
            if not state.pending_findings:
                self._event(
                    state, "evidence_verifier", "agent_skipped", "No pending findings"
                )
        if state.turn_progress is None:
            action = self._supervisor_action(state)
            state.turn_progress = TurnProgress(action=action)
            self.memory.save(state)
        else:
            action = state.turn_progress.action
            self._event(
                state, "supervisor", "decision_reused", action.reason,
                selected_action=action.action,
            )
        return action

    def run_turn(self, state: RunState) -> RunState:
        """Execute one supervisor turn and at most one eligible worker."""
        if state.status != "running":
            return state
        if turn_budget_exhausted(state):
            state.status = "incomplete"
            self._event(
                state, "harness", "budget_exhausted", "Unfinished work remains",
                remaining_chunk_ids=state.remaining_chunk_ids,
            )
            self.memory.save(state)
            return state
        action = self._turn_action(state)
        legal = action.action in eligible_actions(state)
        if action.action == "compare":
            legal = legal and action.reference_paper_id in (
                set(state.scope.reference_versions) - set(state.reference_assessments)
            )
        if not legal:
            self._event(
                state,
                action.action,
                "agent_skipped",
                "Scheduling guard rejected action",
            )
        elif action.action == "next_batch":
            self.memory.save(state)
            queue = DocumentQueue(
                self.memory, batch_size=1 if state.llm_mode == "groq" else 2
            )
            batch = queue.next_main_batch(state.run_id)
            state.current_batch_ids = batch.chunk_ids
            state.batch_count += 1
            self._event(state, "harness", "batch_selected", source_ids=batch.chunk_ids)
        elif action.action == "finish":
            unresolved_questions = [
                item for item in state.findings
                if item["kind"] == "question" and item["status"] != "grounded"
            ]
            for question in unresolved_questions:
                self._event(
                    state, "harness", "question_omitted",
                    "Question lacks verified source support",
                    finding_id=question["id"], reason=question["verdict"],
                )
            state.findings = [
                item for item in state.findings
                if item["kind"] != "question" or item["status"] == "grounded"
            ]
            state.status = "completed"
            self._event(
                state, "harness", "run_completed", "All required work accounted for"
            )
        else:
            gateway = ToolGateway(self.catalog, self.events, state.run_id)
            if action.action == "analyze":
                self._analyze(state, gateway)
            elif action.action == "compare":
                self._compare(state, gateway, action.reference_paper_id)
            elif action.action == "verify":
                self._verify(state, gateway)
            elif action.action == "repair":
                self._repair(state, gateway)
            elif action.action == "audit_omission":
                self._audit_omission(state, gateway)
        state.turn_progress = None
        self._event(
            state,
            "memory",
            "checkpoint_saved",
            processed=len(state.processed_chunk_ids),
            remaining=len(state.remaining_chunk_ids),
            batch=state.batch_count,
        )
        self.memory.save(state)
        return state
