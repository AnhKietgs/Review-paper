"""One background harness turn at a time, checkpointed atomically."""

from datetime import datetime, timezone
from threading import Event, Lock, Thread

from sqlalchemy import select, text

from app.agents.ports import LLMFailure
from app.core.config import Settings
from app.harness.events import RunEventInput, RunEventRecorder
from app.harness.memory import RunMemory
from app.harness.output_gate import OutputGate
from app.harness.runner import AgentRunner
from app.infrastructure.groq.client import GroqClient
from app.infrastructure.groq.fixture_client import FixtureClient
from app.infrastructure.groq.router import GroqRouter
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

    @staticmethod
    def _freeze_review(session, review: ReviewRow, state) -> None:
        """Save a report with unsupported or invalid evidence clearly labeled."""
        gate = OutputGate(SqlSourceCatalog(session))
        for finding in session.scalars(
            select(FindingRow).where(FindingRow.review_id == review.id)
        ):
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
    def recover_interrupted() -> None:
        """Recover interrupted runs and completed reports from older versions."""
        with UnitOfWork() as unit:
            for row in unit.session.scalars(
                select(RunRow).where(RunRow.status == "running")
            ):
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
        try:
            run_id = self._claim()
            if run_id is None:
                return False
            with UnitOfWork() as unit:
                state = RunMemory(unit.session).load(run_id)
                original_steps = state.turn_count
                catalog = SnapshotCatalog(SqlSourceCatalog(unit.session), state.scope)
            original = state.model_copy(deep=True)
            memory, events = RunMemory(), RunEventRecorder()
            memory.save(state)
            settings = Settings.from_env()
            llm = FixtureClient()
            try:
                if state.llm_mode == "groq":
                    if not settings.groq_api_key:
                        raise LLMFailure("missing_groq_key")

                    def retry_event(role: str):
                        def record(attempt: int, wait_seconds: int) -> None:
                            events.append(
                                run_id,
                                RunEventInput(
                                    agent=role,
                                    action="provider_retry",
                                    output_summary=(
                                        f"Rate limited; waiting {wait_seconds}s, "
                                        f"then retry {attempt}"
                                    ),
                                    payload={"wait_seconds": wait_seconds},
                                ),
                            )

                        return record

                    models = {
                        "supervisor": settings.groq_supervisor_model,
                        "scientific_review": settings.groq_scientific_review_model,
                        "related_work": settings.groq_related_work_model,
                        "evidence_verifier": settings.groq_evidence_verifier_model,
                    }
                    completion_budgets = {
                        "supervisor": 256,
                        "scientific_review": 3072,
                        "related_work": 2048,
                        "evidence_verifier": 4096,
                    }
                    llm = GroqRouter(
                        {
                            role: GroqClient(
                                settings.groq_api_key,
                                model,
                                rate_limit_wait_seconds=(
                                    settings.groq_rate_limit_wait_seconds
                                ),
                                max_completion_tokens=completion_budgets[role],
                                on_retry=retry_event(role),
                            )
                            for role, model in models.items()
                        }
                    )
                state = AgentRunner(llm, catalog, memory, events).run_turn(state)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Worker boundary: isolate provider/internal failures from HTTP threads.
                state = original
                state.status = "failed"
                state.error_code = (
                    str(exc) if isinstance(exc, LLMFailure) else "execution_failed"
                )
                events.append(
                    run_id,
                    RunEventInput(
                        agent="harness",
                        action="run_failed",
                        output_summary=state.error_code,
                    ),
                )
            self._persist(state, events, llm.usage, original_steps)
            return True
        finally:
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
