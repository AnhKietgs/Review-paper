"""One background harness turn at a time, checkpointed atomically."""

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread

from sqlalchemy import select, text

from app.agents.ports import LLMFailure, ProviderFailure, RateLimitPause
from app.core.config import Settings
from app.harness.events import RunEventInput, RunEventRecorder
from app.harness.activity import LIVE_ACTIVITY
from app.harness.memory import RunMemory
from app.harness.output_gate import OutputGate
from app.harness.runner import AgentRunner
from app.harness.token_budget import RunTokenBudget
from app.infrastructure.groq.client import GroqClient
from app.infrastructure.groq.fixture_client import FixtureClient
from app.infrastructure.groq.router import GroqRouter
from app.infrastructure.groq.quota import GroqQuota
from app.infrastructure.persistence.orm_models import FindingRow, ReviewRow, RunRow
from app.infrastructure.persistence.source_catalog import SqlSourceCatalog
from app.infrastructure.persistence.unit_of_work import UnitOfWork
from app.services.report_composer import ReportComposer
from app.services.review_service import ReviewService

TURN_LOCK = Lock()


class SnapshotCatalog:
    """Source snapshot lets the model run without holding a SQLite write lock."""

    def __init__(self, catalog, scope):
        versions = {scope.main_paper_id: scope.main_version, **scope.reference_versions}
        self.active = {paper_id: catalog.is_active(paper_id) for paper_id in versions}
        self.sources = {
            item["id"]: item
            for paper_id, version in versions.items()
            for item in catalog.chunks(paper_id, version)
        }
        self.rubric = catalog.criteria(scope.rubric_id, scope.rubric_version)

    def is_active(self, paper_id):
        """Check availability at the start of this turn."""
        return self.active.get(paper_id, False)

    def chunk(self, chunk_id):
        """Return only sources included in the frozen run scope."""
        return self.sources.get(chunk_id)

    def chunks(self, paper_id, version):
        """Return versioned source chunks."""
        return [
            item
            for item in self.sources.values()
            if item["paper_id"] == paper_id and item["content_version"] == version
        ]

    def criteria(self, _rubric_id, _version):
        """Return the frozen rubric criteria."""
        return self.rubric


class RunWorker:
    """Single local worker; model calls occur outside DB transactions."""

    def __init__(self):
        self.stop_event = Event()
        self.thread = None
        settings = Settings.from_env()
        self.quota = GroqQuota(
            tokens_per_minute=settings.groq_tokens_per_minute,
            requests_per_minute=settings.groq_requests_per_minute,
        )

    def _create_groq_router(self, settings, run_id, events, budget=None):
        """Rebuild adapters while keeping one shared model quota across turns."""
        def retry_event(role):
            def record(attempt, wait_seconds):
                events.append(run_id, RunEventInput(
                    agent=role, action="provider_retry",
                    output_summary=(
                        f"Waiting for quota {wait_seconds}s, then retry {attempt}"
                    ),
                    payload={"wait_seconds": wait_seconds},
                ))
            return record

        def quota_event(role):
            def record(payload):
                waiting = payload["wait_seconds"] > 0
                events.append(run_id, RunEventInput(
                    agent=role,
                    action="quota_wait" if waiting else "quota_reserved",
                    output_summary=(
                        f"Waiting {payload['wait_seconds']}s for shared model quota"
                        if waiting else "Input estimate + output budget reserved"
                    ),
                    payload=payload,
                ))
            return record

        def provider_event(role):
            def record(payload):
                retrying = payload["retrying"]
                events.append(run_id, RunEventInput(
                    agent=role,
                    action="provider_transient_retry" if retrying else "provider_error",
                    output_summary=payload["error_code"], payload=payload,
                ))
            return record

        models = {
            "supervisor": (settings.groq_supervisor_model, 256),
            "scientific_extract": (settings.groq_scientific_extraction_model, 768),
            "scientific_synthesis": (settings.groq_scientific_review_model, 1024),
            "scientific_review": (settings.groq_scientific_review_model, 3072),
            "related_work": (settings.groq_related_work_model, 2048),
            # Keep enough completion room for model reasoning plus structured
            # JSON; lower caps caused malformed/truncated verifier responses.
            "evidence_verifier": (settings.groq_evidence_verifier_model, 2560),
        }

        def logical_role(role):
            return "scientific_review" if role in {
                "scientific_extract", "scientific_synthesis",
            } else role

        return GroqRouter({
            role: GroqClient(
                settings.groq_api_key, model,
                rate_limit_wait_seconds=settings.groq_rate_limit_wait_seconds,
                max_completion_tokens=output_limit,
                on_retry=retry_event(logical_role(role)),
                quota=self.quota, on_quota=quota_event(logical_role(role)),
                is_cancelled=lambda: self._is_cancelled(run_id),
                on_provider_event=provider_event(logical_role(role)),
                budget=budget,
                reasoning_effort="low" if role == "scientific_extract"
                and model.startswith("openai/gpt-oss-") else None,
            )
            for role, (model, output_limit) in models.items()
        })

    @staticmethod
    def _is_cancelled(run_id: str) -> bool:
        """Read cancellation outside provider calls without holding a write lock."""
        with UnitOfWork() as unit:
            row = unit.session.get(RunRow, run_id)
            return row is None or row.status == "cancelled"

    @staticmethod
    def _freeze_review(session, review: ReviewRow, state) -> None:
        """Save a report with unsupported or invalid evidence clearly labeled."""
        catalog = SqlSourceCatalog(session)
        gate = OutputGate(catalog)
        main_chunk_ids = {
            item["id"] for item in catalog.chunks(
                state.scope.main_paper_id, state.scope.main_version
            )
        }
        full_coverage = (
            bool(main_chunk_ids)
            and main_chunk_ids == set(state.processed_chunk_ids)
            and not state.remaining_chunk_ids
            and not state.current_batch_ids
        )
        for finding in session.scalars(
            select(FindingRow).where(FindingRow.review_id == review.id)
        ):
            if finding.kind == "omission" and finding.status in {
                "not_reported", "uncertain",
            }:
                if not full_coverage:
                    finding.status = "uncertain"
                    finding.verdict = "Chưa đủ phạm vi đọc để kết luận."
                continue
            draft = {
                key: getattr(finding, key)
                for key in (
                    "id", "criterion_code", "claim", "kind",
                    "compared_paper_ids", "evidence",
                )
            }
            if not gate.validate(draft, state.scope).passed:
                finding.status = "unsupported"
                finding.verdict = (
                    f"{finding.verdict}; nguồn trích dẫn không qua kiểm tra"
                ).strip("; ")
                finding.evidence = []
        session.flush()
        review.status = "completed"
        report = ReportComposer().render_markdown(
            ReviewService(session).get(review.id)
        )
        review.approved_markdown = (
            f"> Chế độ tạo: **{state.llm_mode}**. "
            + (
                "Fixture minh họa luồng; không phải kết quả AI trực tiếp.\n\n"
                if state.llm_mode == "fixture"
                else "Báo cáo do AI tự kiểm tra; nhận xét chưa xác minh được "
                "ghi riêng.\n\n"
            )
            + report
        )

    @staticmethod
    def _recover_budget(unit, row, state) -> bool:
        """Legacy cooldowns must not defer enforcement of a depleted run budget."""
        state.token_spent = max(state.token_spent, row.usage.get("tokens", 0))
        if state.llm_mode != "groq" or state.token_spent < state.token_budget:
            return False
        row.status = state.status = "incomplete"
        row.error_code = state.error_code = "review_token_budget_exhausted"
        row.finished_at = datetime.now(timezone.utc)
        state.cooldown_until = None
        RunMemory(unit.session).save(state)
        RunEventRecorder(unit.session).append(row.id, RunEventInput(
            agent="harness", action="review_budget_exhausted",
            output_summary="Recorded spending already exceeds the review allowance",
            payload={"limit": state.token_budget, "spent": state.token_spent},
        ))
        return True

    @staticmethod
    def recover_interrupted() -> None:
        """Recover interrupted runs and completed reports from older versions."""
        with UnitOfWork() as unit:
            for row in unit.session.scalars(
                select(RunRow).where(RunRow.status == "running")
            ):
                state = RunMemory(unit.session).load(row.id)
                if RunWorker._recover_budget(unit, row, state):
                    continue
                if state.cooldown_until is not None:
                    continue
                row.status = "interrupted"
                RunEventRecorder(unit.session).append(
                    row.id,
                    RunEventInput(
                        agent="harness",
                        action="run_interrupted",
                        output_summary="Process restarted",
                    ),
                )
            for run in unit.session.scalars(
                select(RunRow).where(RunRow.status == "completed")
            ):
                review = unit.session.get(ReviewRow, run.review_id)
                if (
                    review is None or review.deleted_at is not None
                    or review.status != "draft"
                    or review.approved_markdown or review.reviewer_edits
                ):
                    continue
                findings = list(unit.session.scalars(
                    select(FindingRow).where(FindingRow.review_id == review.id)
                ))
                if any(item.status == "pending" for item in findings):
                    continue
                state = RunMemory(unit.session).load(run.id)
                RunWorker._freeze_review(unit.session, review, state)

    @staticmethod
    def _claim() -> str | None:
        with UnitOfWork() as unit:
            unit.session.execute(text("BEGIN IMMEDIATE"))
            row = unit.session.scalar(select(RunRow).where(RunRow.status == "running"))
            if row is not None:
                state = RunMemory(unit.session).load(row.id)
                if (
                    state.cooldown_until is not None
                    and state.cooldown_until > datetime.now(timezone.utc)
                ):
                    return None
            if row is None:
                row = unit.session.scalar(
                    select(RunRow)
                    .where(RunRow.status == "queued")
                    .order_by(RunRow.created_at)
                    .limit(1)
                )
                if row is not None:
                    row.status = "running"
                    row.started_at = row.started_at or datetime.now(timezone.utc)
            return row.id if row else None

    @staticmethod
    def _persist(state, events, usage, original_steps):
        with UnitOfWork() as unit:
            unit.session.execute(text("BEGIN IMMEDIATE"))
            run = unit.session.get(RunRow, state.run_id)
            if run.status != "running" or run.step_count != original_steps:
                return
            run.status = state.status
            run.step_count = state.turn_count
            run.error_code = state.error_code
            run.usage = {
                key: run.usage.get(key, 0) + value for key, value in usage.items()
            }
            if state.status != "running":
                run.finished_at = datetime.now(timezone.utc)
            review = unit.session.get(ReviewRow, state.review_id)
            review.analysis = {
                "workflow": {
                    "two_phase_review": state.two_phase_review,
                    "note_count": len(state.read_notes),
                    "max_repairs": state.max_repairs,
                    "max_omission_topics": state.max_omission_topics,
                },
                "sections": state.analysis,
                "references": state.reference_assessments,
                "coverage": {
                    "processed": len(state.processed_chunk_ids),
                    "remaining": len(state.remaining_chunk_ids),
                },
            }
            if "summary" not in review.reviewer_edits:
                review.summary = "\n".join(state.analysis.get("objective", []))
            current_ids = {item["id"] for item in state.findings}
            for old in unit.session.scalars(
                select(FindingRow).where(FindingRow.review_id == review.id)
            ):
                if old.id not in current_ids:
                    unit.session.delete(old)
            for item in state.findings:
                row = unit.session.get(FindingRow, item["id"])
                values = {
                    key: item[key]
                    for key in (
                        "criterion_code",
                        "claim",
                        "kind",
                        "compared_paper_ids",
                        "evidence",
                        "status",
                        "verdict",
                    )
                }
                if row is None:
                    unit.session.add(
                        FindingRow(id=item["id"], review_id=review.id, **values)
                    )
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
            unit.session.flush()
            if state.status == "completed":
                RunWorker._freeze_review(unit.session, review, state)
            recorder = RunEventRecorder(unit.session)
            for event in events.items:
                recorder.append(
                    state.run_id,
                    RunEventInput.model_validate(
                        {
                            key: event[key]
                            for key in (
                                "agent",
                                "action",
                                "tool",
                                "permission_result",
                                "input_summary",
                                "output_summary",
                                "payload",
                            )
                        }
                    ),
                )
            RunMemory(unit.session).save(state)

    def tick(self) -> bool:
        """Claim or advance one run; concurrent ticks do no work."""
        if not TURN_LOCK.acquire(blocking=False):  # pylint: disable=consider-using-with
            return False
        run_id = None
        try:
            run_id = self._claim()
            if run_id is None:
                return False
            with UnitOfWork() as unit:
                state = RunMemory(unit.session).load(run_id)
                state.cooldown_until = None
                if state.llm_mode == "groq" and state.turn_progress is None:
                    state.efficient_review = True
                original_steps = state.turn_count
                recorded_usage = unit.session.get(RunRow, run_id).usage.get("tokens", 0)
                state.token_spent = max(state.token_spent, recorded_usage)
                catalog = SnapshotCatalog(SqlSourceCatalog(unit.session), state.scope)
            memory = RunMemory()
            events = RunEventRecorder(
                on_event=lambda _run_id, event: LIVE_ACTIVITY.publish(state, event),
            )
            LIVE_ACTIVITY.publish(state)
            memory.save(state)
            settings = Settings.from_env()
            budget = RunTokenBudget(state.token_budget, state.token_spent)
            llm = FixtureClient()
            try:
                if state.llm_mode == "groq":
                    if not settings.groq_api_key:
                        raise LLMFailure("missing_groq_key")
                    llm = self._create_groq_router(settings, run_id, events, budget)
                state = AgentRunner(llm, catalog, memory, events).run_turn(state)
            except RateLimitPause as exc:
                state = memory.load(run_id)
                state.cooldown_until = datetime.now(timezone.utc) + timedelta(
                    seconds=exc.retry_after_seconds
                )
                events.append(
                    run_id,
                    RunEventInput(
                        agent="harness",
                        action="provider_cooldown",
                        output_summary=(
                            f"Groq limit reached; resuming in "
                            f"{exc.retry_after_seconds}s"
                        ),
                        payload={
                            "retry_after_seconds": exc.retry_after_seconds,
                            "cooldown_until": state.cooldown_until.isoformat(),
                            "provider_rate_limits": exc.provider_details,
                            "resume_action": (
                                state.turn_progress.action.action
                                if state.turn_progress is not None else None
                            ),
                        },
                    ),
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Worker boundary: isolate provider/internal failures from HTTP threads.
                state = memory.load(run_id)
                state.status = "failed"
                state.error_code = (
                    str(exc) if isinstance(exc, LLMFailure) else "execution_failed"
                )
                if state.error_code == "review_token_budget_exhausted":
                    state.status = "incomplete"
                events.append(
                    run_id,
                    RunEventInput(
                        agent="harness",
                        action=(
                            "review_budget_exhausted" if state.status == "incomplete"
                            else "run_failed"
                        ),
                        output_summary=state.error_code,
                        payload={
                            "provider_failure": exc.details,
                            "retryable": exc.retryable,
                        } if isinstance(exc, ProviderFailure) else {},
                    ),
                )
            state.token_spent = budget.spent
            self._persist(state, events, llm.usage, original_steps)
            return True
        finally:
            if run_id is not None:
                LIVE_ACTIVITY.clear(run_id)
            TURN_LOCK.release()

    def _loop(self):
        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(0.25)

    def start(self) -> None:
        """Start exactly one local processing thread."""
        self.recover_interrupted()
        self.thread = Thread(target=self._loop, name="paper-review-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Finish the current bounded provider call then stop."""
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=35)
