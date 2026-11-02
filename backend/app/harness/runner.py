"""Bounded loop owned by the harness, with one worker per turn."""

from uuid import uuid4

from app.agents.graph_factory import AgentFactory
from app.agents.schemas import FindingDraft
from app.agents.supervisor import Supervisor, eligible_actions
from app.harness.context import ContextBuilder
from app.harness.document_queue import DocumentQueue
from app.harness.events import RunEventInput, RunEventRecorder
from app.harness.memory import RunMemory
from app.harness.output_gate import OutputGate
from app.harness.state import RunState
from app.harness.tool_gateway import ToolCall, ToolGateway


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

    def _graph(self, role: str):
        if role not in self.graphs:
            model = (
                self.llm.for_role(role)
                if hasattr(self.llm, "for_role")
                else self.llm
            )
            self.graphs[role] = AgentFactory.build(role, model)
        return self.graphs[role]

    def _model_id(self, role: str) -> str:
        """Expose only the selected model ID, never provider credentials."""
        if hasattr(self.llm, "model_for"):
            return self.llm.model_for(role)
        return "fixture" if self.llm.__class__.__name__ == "FixtureClient" else "custom"

    def _invoke(self, state: RunState, role: str, context: dict) -> dict:
        self._event(state, role, "agent_started", model=self._model_id(role))
        state.call_counts[role] = state.call_counts.get(role, 0) + 1
        output = self._graph(role).invoke({"context": context})["output"]
        self._event(state, role, "agent_finished", "Structured output received")
        return output

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
            {"finding_id": finding["id"], "role": role, "source_ids": source_ids}
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
                state.findings.append(
                    {
                        **finding,
                        "evidence": [],
                        "status": "unsupported",
                        "verdict": ", ".join(result.reason_codes),
                    }
                )
                self._queue_repair(state, finding, role, source_ids)

    def _context(
        self,
        state: RunState,
        gateway: ToolGateway,
        role: str,
        ids: list[str],
        extra: list[dict] | None = None,
    ) -> dict:
        result = gateway.execute(
            ToolCall(agent=role, name="read_chunks", arguments={"chunk_ids": ids}),
            state.scope,
        )
        if not result.allowed:
            raise ValueError("Source permission denied")
        rubric = gateway.execute(
            ToolCall(agent="supervisor", name="read_rubric"), state.scope
        )
        context = self.context_builder.build(
            state, result.data + (extra or []), rubric.data
        )
        self._event(
            state,
            "context",
            "context_built",
            f"Context for {role}",
            source_ids=[item["id"] for item in context["chunks"]],
        )
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

    def _verify(self, state: RunState, gateway: ToolGateway) -> None:
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
        ]
        if not candidates:
            self._event(state, role, "repair_unresolved", "No supported revision")
            return
        candidate = candidates[0]
        candidate["id"] = str(uuid4())
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
        state.repair_attempted_ids.append(candidate["id"])
        state.pending_findings.append(candidate)
        self._event(
            state, role, "finding_repaired", "Revision sent to Evidence Verifier",
            original_finding_id=original["id"], finding_id=candidate["id"],
        )

    def run_turn(self, state: RunState) -> RunState:
        """Execute one supervisor turn and at most one eligible worker."""
        if state.status != "running":
            return state
        if state.turn_count >= state.max_turns or (
            state.batch_count >= state.max_batches
            and state.remaining_chunk_ids
            and not state.current_batch_ids
            and not state.pending_findings
        ):
            state.status = "incomplete"
            self._event(
                state,
                "harness",
                "budget_exhausted",
                "Unfinished work remains",
                remaining_chunk_ids=state.remaining_chunk_ids,
            )
            self.memory.save(state)
            return state
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
        self._event(
            state, "supervisor", "agent_started", model=self._model_id("supervisor")
        )
        state.call_counts["supervisor"] = state.call_counts.get("supervisor", 0) + 1
        action = Supervisor(self._graph("supervisor")).decide(state)
        self._event(
            state,
            "supervisor",
            "decision",
            action.reason,
            selected_action=action.action,
        )
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
