# Paper Review MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây MVP Paper Review chạy local bằng Docker Compose, có CRUD REST/MVC, bốn agent LangGraph hoạt động theo nhu cầu trong harness tự xây, PDF/DOCX → Markdown có dẫn chứng truy về nguồn, và báo cáo được người dùng duyệt.

**Architecture:** Next.js là View; FastAPI controller gọi application services và domain/repository. DocumentIngress dùng MarkItDown cùng bộ định vị nguồn. AgentRunner của harness gọi Supervisor trước mỗi lượt, chỉ kích hoạt một worker đủ điều kiện, kiểm soát tool, memory, context, output và trace. SQLite/tệp/checkpoint nằm trong Docker named volume.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, Pydantic, LangGraph, Groq API, MarkItDown với extras PDF/DOCX, pytest, Pylint, pycodestyle; Node.js 24 LTS, Next.js/React; Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-26-ai-paper-review-design.md`

## Global Constraints

- Chỉ thực hiện M1–M6; M6E, Literature Review và tìm kiếm Internet có kế hoạch riêng.
- MVP local một người dùng, không đăng nhập; chỉ nhận PDF có lớp văn bản và DOCX; không OCR hoặc tự tìm paper.
- Docker Compose có đúng hai service `backend` và `frontend`; SQLite, upload, Markdown, checkpoint nằm trong named volume `app_data`.
- `GET/POST/PATCH/DELETE` của Paper, Rubric, Review tuân thủ REST và status code trong spec; router không chứa nghiệp vụ.
- Bốn agent: Supervisor, Scientific Review, Related-Work Comparator, Evidence Verifier. Mỗi lượt chỉ gọi một worker, worker bỏ qua không gọi Groq.
- Giới hạn mặc định 20 batch paper chính và 80 agent turns/run; vượt giới hạn chuyển `incomplete` và hiển thị phần chưa xử lý.
- Paper chính phải được xử lý hết; mỗi paper đối chiếu được đánh giá ít nhất một batch liên quan hoặc ghi `not_assessed` và lý do. Run hết budget là `incomplete`.
- Finding mới/sửa phải qua Evidence Verifier trước khi thành `supported`; quote/locator phải truy về tài liệu gốc. Report đã duyệt không chứa `unsupported` như nhận xét có căn cứ.
- `DEMO_LLM_MODE=fixture` và `groq` dùng cùng harness; UI ghi rõ chế độ. Groq key chỉ ở backend, không trong trace/frontend.
- Python đạt `pytest`, `pylint` và `pycodestyle`; frontend đạt lint/build; demo được kiểm tra sau `docker compose down` rồi `up`.

## Review Focus

1. PDF không có lớp văn bản hoặc DOCX không thể định vị quote → trả lỗi nhập liệu/`unresolved_locator`, không tạo finding `supported`. Kiểm tra ở Task 3 và 8.
2. Paper đối chiếu bị xóa mềm, trùng paper chính hoặc ngoài review → không được đọc qua ToolGateway; REST trả 404/422 theo trường hợp. Kiểm tra ở Task 6 và 7.
3. Supervisor yêu cầu Comparator khi không có paper liên quan hoặc Verifier khi không có finding → ghi `agent_skipped`, không gọi Groq. Kiểm tra ở Task 9.
4. Container khởi động lại giữa run → giữ checkpoint, chuyển `interrupted`, chỉ chạy tiếp qua resume; không nhân đôi finding. Kiểm tra ở Task 10 và 13.
5. Dẫn chứng quote đúng chuỗi nhưng từ paper/phiên bản khác hoặc so sánh thiếu một phía → không được `supported`; không xuất bản như đã xác minh. Kiểm tra ở Task 8 và 11.

---

## File Map

| Khu vực | File chính | Trách nhiệm |
|---|---|---|
| Local stack | `compose.yaml`, `backend/Dockerfile`, `backend/docker/entrypoint.sh`, `frontend/Dockerfile`, `.env.example` | build, migration, cổng 3000/8000, `app_data`, healthcheck |
| Controller/View | `backend/app/api/v1/controllers/*.py`, `backend/app/api/v1/schemas/*.py`, `frontend/src/app/**`, `frontend/src/components/**` | HTTP, validation, giao diện; không chứa nghiệp vụ |
| Domain | `backend/app/domain/models/*.py`, `backend/app/domain/policies/*.py`, `backend/app/domain/repositories/*.py` | thực thể, trạng thái, repository ports |
| Services | `backend/app/services/*.py` | CRUD, tạo run, duyệt và xuất report |
| Ingestion | `backend/app/ingestion/*.py` | MarkItDown, PDF/DOCX locator, chunk |
| Harness | `backend/app/harness/*.py` | loop, queue, tool, context, memory, output, event |
| Agents | `backend/app/agents/*.py`, `backend/app/agents/prompts/*` | bốn LangGraph subgraph, kết quả có schema |
| Infrastructure | `backend/app/infrastructure/{persistence,groq,storage}/**`, `backend/migrations/**` | SQLite/SQLAlchemy, Groq adapter, file store |
| Background run | `backend/app/workers/run_worker.py` | tối đa một run active, checkpoint, resume |
| Verification/demo | `backend/tests/**`, `frontend/tests/**`, `backend/app/demo/seed.py`, `demo_data/**`, `README.md` | hành vi có rủi ro, fixture và hướng dẫn |

## Task 1: Bootstrap Docker, MVC skeleton and health

**Files:** Create `compose.yaml`, `.env.example`, `.gitignore`, `backend/Dockerfile`, `backend/.dockerignore`, `backend/docker/entrypoint.sh`, `backend/pyproject.toml`, `backend/alembic.ini`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/app/api/v1/controllers/health.py`, `frontend/Dockerfile`, `frontend/.dockerignore`, `frontend/package.json`, `frontend/next.config.ts`, `frontend/src/app/page.tsx`, `backend/tests/api/test_health.py`; initialize Git because this workspace currently has no `.git`.

**Interfaces:** Produces `GET /api/v1/health -> {"status":"ok"}`, `GET /api/v1/runtime -> {"llm_mode":"fixture"|"groq"}` (không lộ key); `Settings(data_dir: Path, demo_llm_mode: Literal["fixture","groq"], groq_api_key: str | None)`; Compose services named `backend`/`frontend`, named volume `app_data` mounted at `/app/data`. Next.js rewrites `/api/v1/*` to `http://backend:8000/api/v1/*` so browser uses same origin.

- [ ] **Step 1: Write failing smoke test.** `test_health_returns_ok` asserts GET `/api/v1/health` returns 200 and exact JSON `{"status":"ok"}`; `test_runtime_exposes_mode_only` asserts `fixture` without exposing `GROQ_API_KEY`.
- [ ] **Step 2: Run `pytest backend/tests/api/test_health.py -q`.** Expected failure: app/route does not exist.
- [ ] **Step 3: Implement minimal skeleton and Compose.** Python 3.12 and Node 24 images; backend entrypoint serves FastAPI (migration is added in Task 2); frontend serves Next.js; `.env.example` defaults to `fixture`; backend healthcheck; volume `/app/data`.
- [ ] **Step 4: Verify.** `pytest backend/tests/api/test_health.py -q`, then `docker compose up --build -d`; GET `http://localhost:8000/api/v1/health` and proxied `http://localhost:3000/api/v1/health` return 200, `http://localhost:3000` loads, `docker compose ps` shows healthy backend. `docker compose down` stops without deleting volume.
- [ ] **Step 5: Initialize Git if needed and commit** the skeleton with message `chore: bootstrap local Docker MVP`.

## Task 2: Persistence foundation and REST error contract

**Files:** Create `backend/app/infrastructure/persistence/{database.py,orm_models.py,unit_of_work.py}`, `backend/app/api/v1/schemas/common.py`, `backend/app/core/errors.py`, `backend/migrations/{env.py,versions/0001_initial.py}`, `backend/tests/api/test_error_contract.py`; modify `backend/docker/entrypoint.sh`.

**Interfaces:** Produces `UnitOfWork` context manager and `get_uow() -> UnitOfWork`; `NotFoundError`, `ConflictError`, `ValidationError` mapped to 404, 409, 422. ORM tables cover spec entities (`papers`, `paper_chunks`, `source_locators`, `rubrics`, `criteria`, `reviews`, `review_references`, `findings`, `runs`, `run_events`, `run_checkpoints`).

- [ ] **Step 1: Write failing tests.** `test_domain_errors_map_to_rest_status` asserts 404/409/422 and stable JSON `code`, `detail`; `test_migration_creates_core_tables` checks schema on empty SQLite.
- [ ] **Step 2: Run `pytest backend/tests/api/test_error_contract.py -q`.** Expected fail: handlers/migration absent.
- [ ] **Step 3: Implement DB session, migration and error mapping.** Entry point runs `alembic upgrade head` before FastAPI; Controller receives UoW via FastAPI dependency; no DB access in route body.
- [ ] **Step 4: Run `pytest backend/tests/api/test_error_contract.py -q` and `alembic upgrade head`.** Expected all tables and status contracts pass.
- [ ] **Step 5: Commit** `feat: add persistence and API error contract`.

## Task 3: PDF/DOCX conversion with source locations

**Files:** Create `backend/app/domain/models/{paper.py,source.py}`, `backend/app/ingestion/{markitdown_adapter.py,pdf_locator.py,docx_locator.py,chunker.py,document_ingress.py}`, `backend/tests/ingestion/{test_pdf_ingress.py,test_docx_ingress.py}`, `demo_data/{main_sample.pdf,related_sample.docx,scanned_sample.pdf}`.

**Interfaces:** Produces `DocumentIngress.ingest(file_path: Path, paper_id: UUID, content_version: int) -> IngestedDocument`; `IngestedDocument(markdown: str, chunks: list[PaperChunk], locators: list[SourceLocator])`. A locator is `pdf_page` or `docx_paragraph`; unresolved mapping uses `unresolved_locator` status and cannot prove a claim.

- [ ] **Step 1: Write failing ingestion tests.** PDF fixture has a phrase on page 2; assert its chunk locator is `pdf_page=2`. DOCX fixture has phrase in paragraph 3; assert `docx_paragraph=3`. Scanned PDF fixture has no text; assert explicit conversion failure. Ambiguous quote mapping asserts unresolved.
- [ ] **Step 2: Run `pytest backend/tests/ingestion -q`.** Expected fail: ingress absent.
- [ ] **Step 3: Implement MarkItDown adapter plus independent page/paragraph extractors.** Preserve original file hash, normalized Markdown span and content version. Limit accepted types to PDF/DOCX.
- [ ] **Step 4: Run ingestion tests.** Inspect actual fixture output manually once to ensure locator points to original document, not just Markdown.
- [ ] **Step 5: Commit** `feat: ingest PDF and DOCX with source locators`.

## Task 4: Paper CRUD and stored content versions

**Files:** Create `backend/app/domain/repositories/papers.py`, `backend/app/infrastructure/persistence/paper_repository.py`, `backend/app/infrastructure/storage/local_files.py`, `backend/app/services/paper_service.py`, `backend/app/api/v1/{controllers/papers.py,schemas/papers.py}`, `backend/tests/api/test_papers.py`; modify `backend/app/main.py`.

**Interfaces:** Produces `PaperService.create(upload: UploadFile, metadata: PaperCreate) -> PaperRead`, `get/list/update/delete`; `PaperRepository` port. `POST /api/v1/papers` accepts multipart; `PATCH` metadata/file replacement creates new `content_version`; `DELETE` soft deletes.

- [ ] **Step 1: Write failing CRUD test.** Create PDF → 201 + Location; list/detail → 200; update title → 200; replace file → version increments and old chunks remain referenced; delete → 204 then normal GET → 404. Unsupported extension → 422.
- [ ] **Step 2: Run `pytest backend/tests/api/test_papers.py -q`.** Expected fail: route/service absent.
- [ ] **Step 3: Implement service/repository/controller.** Save file under `/app/data/uploads`, invoke Task 3 ingress, commit metadata/chunks/locators atomically.
- [ ] **Step 4: Run Paper tests and verify restart.** `docker compose down`/`up -d`; created paper and file still readable.
- [ ] **Step 5: Commit** `feat: add paper CRUD`.

## Task 5: Rubric CRUD, versions and qualitative criteria

**Files:** Create `backend/app/domain/models/rubric.py`, `backend/app/domain/repositories/rubrics.py`, `backend/app/infrastructure/persistence/rubric_repository.py`, `backend/app/services/rubric_service.py`, `backend/app/api/v1/{controllers/rubrics.py,schemas/rubrics.py}`, `backend/tests/api/test_rubrics.py`; modify `backend/app/main.py`.

**Interfaces:** Produces `RubricService.create/get/list/update/delete`; criteria have `code`, `question`, `guidance`, `order_index`, no numeric score. `PATCH` creates new rubric version while old review retains its version.

- [ ] **Step 1: Write failing CRUD/version tests.** Create/list/get/patch/delete with expected 201/200/204/404; duplicate criterion code → 422; patch increments version and preserves prior snapshot.
- [ ] **Step 2: Run `pytest backend/tests/api/test_rubrics.py -q`.** Expected fail: rubric route absent.
- [ ] **Step 3: Implement domain/service/repository/controller.** Controller only maps HTTP to service.
- [ ] **Step 4: Run `pytest backend/tests/api/test_rubrics.py -q` and inspect `/openapi.json`** for schema/status correctness.
- [ ] **Step 5: Commit** `feat: add versioned rubric CRUD`.

## Task 6: Review draft CRUD, selected references and revisions

**Files:** Create `backend/app/domain/models/{review.py,finding.py}`, `backend/app/domain/repositories/reviews.py`, `backend/app/infrastructure/persistence/review_repository.py`, `backend/app/services/review_service.py`, `backend/app/api/v1/{controllers/reviews.py,schemas/reviews.py}`, `backend/tests/api/test_reviews.py`; modify `backend/app/main.py`.

**Interfaces:** Produces `ReviewService.create(paper_id: UUID, rubric_id: UUID, reference_paper_ids: list[UUID]) -> ReviewRead`, `new_revision(review_id: UUID) -> ReviewRead`, `get/list/update/delete`. `ReviewReference` freezes selected paper content version.

- [ ] **Step 1: Write failing tests.** Full CRUD statuses; reference same as main/duplicate → 422; soft-deleted reference → 404; edit review then `new_revision` preserves old revision/findings and returns new ID.
- [ ] **Step 2: Run `pytest backend/tests/api/test_reviews.py -q`.** Expected fail: route/service absent.
- [ ] **Step 3: Implement repository/service/controller.** Restrict `PATCH` to editable draft fields; approved revision cannot be silently overwritten.
- [ ] **Step 4: Run `pytest backend/tests/api/test_reviews.py -q`.** Confirm reference version snapshot survives Paper update.
- [ ] **Step 5: Commit** `feat: add review drafts and reference snapshots`.

## Task 7: Harness queue, memory, tools and permissions

**Files:** Create `backend/app/harness/{state.py,document_queue.py,memory.py,tool_gateway.py,events.py,context.py}`, `backend/app/domain/policies/tool_policy.py`, `backend/tests/harness/{test_document_queue.py,test_tool_gateway.py,test_events.py}`.

**Interfaces:** Produces `DocumentQueue.next_main_batch(run_id: UUID) -> ChunkBatch | None`, `mark_processed(run_id: UUID, chunk_ids: list[UUID])`, `reference_scope(run_id: UUID) -> set[UUID]`; `ToolGateway.execute(call: ToolCall, scope: RunScope) -> ToolResult`; `RunEventRecorder.append(run_id: UUID, event: RunEventInput) -> None`. `RunScope` contains main paper/version, selected reference/version IDs and rubric/version. `RunState` stores processed/remaining IDs, pending findings, reference assessment, turn/batch counts and checkpoint.

- [ ] **Step 1: Write failing tests.** Main paper chunks delivered once and all accounted for; tool outside allowlist or reference outside selected set returns denial event; events sequence monotonically; context never includes Groq key.
- [ ] **Step 2: Run `pytest backend/tests/harness/test_document_queue.py backend/tests/harness/test_tool_gateway.py backend/tests/harness/test_events.py -q`.** Expected fail: classes absent.
- [ ] **Step 3: Implement queue, state persistence and ToolGateway.** Keep permission check before dispatch; no direct tool handler access from agents.
- [ ] **Step 4: Run `pytest backend/tests/harness -q`.** Verify checkpoint reload returns same queue progress.
- [ ] **Step 5: Commit** `feat: add bounded document harness primitives`.

## Task 8: Evidence and output gate

**Files:** Create `backend/app/harness/output_gate.py`, `backend/app/domain/policies/approval.py`, `backend/app/agents/schemas.py`, `backend/tests/harness/test_output_gate.py`.

**Interfaces:** Produces `OutputGate.validate(finding: FindingDraft, scope: RunScope) -> ValidationResult`; `ApprovalPolicy.can_approve(findings: list[Finding]) -> bool`. `ValidationResult` reports schema, paper/version, quote and locator checks separately. Only Evidence Verifier result may promote to `supported`.

- [ ] **Step 1: Write failing tests.** Correct quote/locator in scope passes; quote from another content version, unresolved locator, missing one side of comparison and malformed schema fail. `unsupported` cannot be approved; human-confirmed `needs_human_review` retains label.
- [ ] **Step 2: Run `pytest backend/tests/harness/test_output_gate.py -q`.** Expected fail: gate absent.
- [ ] **Step 3: Implement schema validation and deterministic provenance checks.** Return one repair request at most; preserve reason codes in result.
- [ ] **Step 4: Run `pytest backend/tests/harness/test_output_gate.py -q`.** Verify no test relies on real Groq.
- [ ] **Step 5: Commit** `feat: validate review evidence and approval state`.

## Task 9: Four on-demand LangGraph agents and runner

**Files:** Create `backend/app/agents/{ports.py,supervisor.py,scientific_review.py,related_work.py,evidence_verifier.py,graph_factory.py}`, `backend/app/agents/prompts/*`, `backend/app/infrastructure/groq/{client.py,fixture_client.py}`, `backend/app/harness/runner.py`, `backend/tests/agents/test_agent_runner.py`, `backend/tests/agents/test_groq_adapter.py`.

**Interfaces:** Produces `Supervisor.decide(state: RunState) -> AgentAction`; `AgentRunner.run_turn(state: RunState) -> RunState`; `AgentFactory.build(role: AgentRole, llm: LLMPort) -> CompiledGraph`; `LLMPort.generate_json(messages: list[Message], schema: type[BaseModel]) -> BaseModel` in `agents/ports.py`. Actions are `analyze|compare|verify|next_batch|finish`; only one worker invoked per turn.

- [ ] **Step 1: Write failing tests with spies/fixture LLM.** No reference → Comparator call count 0; no pending finding → Verifier count 0; selected worker alone called; invalid Supervisor action records `agent_skipped`; max 20 main batches/80 turns yields `incomplete`; every selected reference assessed or reasoned `not_assessed` before finish.
- [ ] **Step 2: Run `pytest backend/tests/agents -q`.** Expected fail: graphs/runner absent.
- [ ] **Step 3: Implement four LangGraph subgraphs and runner.** Supervisor returns one structured action; harness rechecks guard; Groq adapter uses model ID from settings and bounded retry on 429; fixture adapter follows same port. Scientific agent handles analysis/critique; Comparator is claim scoped; Verifier returns support assessment; Report Composer remains outside agents.
- [ ] **Step 4: Run `pytest backend/tests/agents -q`.** Manually run one fixture paper through runner and inspect event order. No network required in CI.
- [ ] **Step 5: Commit** `feat: run four agents on demand through harness`.

## Task 10: Background run lifecycle and REST status

**Files:** Create `backend/app/domain/models/run.py`, `backend/app/domain/repositories/runs.py`, `backend/app/infrastructure/persistence/run_repository.py`, `backend/app/workers/run_worker.py`, `backend/app/services/run_service.py`, `backend/app/api/v1/{controllers/runs.py,schemas/runs.py}`, `backend/tests/api/test_runs.py`; modify `backend/app/main.py`.

**Interfaces:** Produces `RunService.start(review_id: UUID) -> RunAccepted`, `get/events/resume`; `POST /api/v1/reviews/{id}/runs -> 202`, `GET /api/v1/runs/{id}`, `GET /api/v1/runs/{id}/events`, `POST /api/v1/runs/{id}/resume -> 202`. One active run; others queued. On restart `running -> interrupted`, manual resume only.

- [ ] **Step 1: Write failing lifecycle tests.** Start → 202 with run/revision IDs; second run queued; restart marks first interrupted without erasing checkpoint; resume advances once; duplicate/completed resume → 409; polling events returns increasing sequence.
- [ ] **Step 2: Run `pytest backend/tests/api/test_runs.py -q`.** Expected fail: endpoints/worker absent.
- [ ] **Step 3: Implement worker and service.** Persist checkpoint after each batch/turn; claim queued work atomically; worker never starts two run loops simultaneously.
- [ ] **Step 4: Run `pytest backend/tests/api/test_runs.py -q` and a container restart check** in fixture mode; confirm no duplicated finding/event.
- [ ] **Step 5: Commit** `feat: add resumable review run lifecycle`.

## Task 11: Approval, deterministic report and Markdown export

**Files:** Create `backend/app/services/{approval_service.py,report_composer.py}`, `backend/app/api/v1/controllers/export.py`, `backend/tests/api/{test_approval.py,test_export.py}`; modify `backend/app/api/v1/controllers/reviews.py`.

**Interfaces:** Produces `ApprovalService.approve(review_id: UUID, confirmations: list[UUID]) -> ReviewRead`; `ReportComposer.render_markdown(review: ReviewRead) -> str`; `POST /api/v1/reviews/{id}/approve`, `GET /api/v1/reviews/{id}/export.md`.

- [ ] **Step 1: Write failing tests.** Draft export → 409; approved export → Markdown with all required sections and source locator; `unsupported` finding blocks approval; human-confirmed `needs_human_review` keeps label; rerun creates new revision and leaves approved version intact.
- [ ] **Step 2: Run `pytest backend/tests/api/test_approval.py backend/tests/api/test_export.py -q`.** Expected fail: approval/export absent.
- [ ] **Step 3: Implement policy and composer.** Compose from validated structured data only, with deterministic ordering; no extra LLM call at export.
- [ ] **Step 4: Run `pytest backend/tests/api/test_approval.py backend/tests/api/test_export.py -q`.** Compare exported Markdown bytes with approved snapshot.
- [ ] **Step 5: Commit** `feat: approve and export evidence review`.

## Task 12: Next.js user flows and harness inspector

**Files:** Create `frontend/src/lib/api/{client.ts,types.ts}`, `frontend/src/app/{papers,rubrics,reviews,runs}/**`, `frontend/src/components/{library,rubric,review,harness}/**`, `frontend/tests/review-flow.spec.ts`, `frontend/playwright.config.ts`; modify `frontend/src/app/page.tsx` and `frontend/package.json`.

**Interfaces:** REST client implements Task 4–11 endpoints. Routes show Library, Rubric editor, Review workspace, Run Inspector and Draft Review. `DEMO_LLM_MODE` appears visibly; browser can open PDF page/DOCX paragraph from finding locator.

- [ ] **Step 1: Write failing browser flow.** Upload/select documents; create rubric; start run; poll status; inspect one `agent_skipped` reason and one tool event; click finding to open source; edit/approve/export. Assert fixture-mode badge.
- [ ] **Step 2: Run `npx playwright test tests/review-flow.spec.ts` from `frontend/`.** Expected fail: routes/components absent.
- [ ] **Step 3: Implement views and REST client.** Frontend holds no Groq key or business permission logic. Use real RunEvent data for diagram/timeline; no synthetic progress.
- [ ] **Step 4: Run `npx playwright test tests/review-flow.spec.ts`, `npm run lint`, `npm run build` from `frontend/`.** Verify responsive readable layout at laptop width.
- [ ] **Step 5: Commit** `feat: add paper review UI and harness inspector`.

## Task 13: Reproducible demo and quality gates

**Files:** Create `backend/app/demo/seed.py`, `demo_data/expected_review.json`, `backend/tests/e2e/test_demo_fixture.py`, `docs/architecture/{mvc.md,harness.md}`, `docs/api/rest-contract.md`, `README.md`; modify `demo_data/{main_sample.pdf,related_sample.docx}`, `.env.example`, `backend/pyproject.toml`, `compose.yaml`.

**Interfaces:** `python -m app.demo.seed` is idempotent. Compose mounts `./demo_data:/app/demo_data:ro` in backend for seeding; `app_data` remains the persistent writable volume. README documents `docker compose up --build -d`, seed command, URLs, `groq`/`fixture`, logs, `down`, and volume preservation. `expected_review.json` is a fixture contract, not a prerecorded trace bypassing harness.

- [ ] **Step 1: Write failing end-to-end fixture test.** Seed twice → one sample rubric/two papers; run Paper Review → completed report with two-sided evidence; bad source ID fixture → validation event and no `supported` finding; no-reference run → Comparator zero calls.
- [ ] **Step 2: Run `pytest backend/tests/e2e/test_demo_fixture.py -q`.** Expected fail until seed/fixture wiring exists.
- [ ] **Step 3: Implement seed, fixture responses and docs.** Add one manual Groq smoke procedure; do not require real API key in CI.
- [ ] **Step 4: Verify final gates.** Run `pytest backend/tests -q`, `pylint backend/app`, `pycodestyle backend/app`, frontend lint/build/browser flow, `docker compose up --build -d`, demo seed, `docker compose down`, `docker compose up -d`. Confirm paper, edits, checkpoint and Markdown export persist.
- [ ] **Step 5: Commit** `docs: ship reproducible Paper Review MVP demo`.

## Self-review and handoff

- [x] Map every M1–M6 requirement in the spec to Tasks 1–13; M6E/M7/M8 are outside this plan.
- [x] Check interfaces (`RunState`, `RunScope`, `FindingDraft`, IDs, statuses) match between producing and consuming tasks.
- [x] Confirm the five Review Focus conditions are covered by tests in Tasks 3, 6–11 and 13.
- [x] Confirm the repo was not a Git checkout when planning; initialize Git only during Task 1 execution.
