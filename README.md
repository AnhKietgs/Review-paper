# Evidence Grounded Paper Review

Local-first MVP for reviewing one scientific paper with evidence that can be opened at its original PDF page or DOCX paragraph. The user uploads the main paper, optionally selects uploaded related work, defines a qualitative rubric and starts an AI review. The harness checks each finding, gives the original agent one bounded repair attempt when needed and creates a Markdown report automatically. Unverified findings are labeled separately. Users may inspect sources or create a new revision to edit the result.

The stack is FastAPI, Next.js/Node.js, LangGraph and Groq API. Four logical agents are hosted by the custom harness: Supervisor, Scientific Review, Related-Work Comparator and Evidence Verifier. The harness calls one worker at a time and controls tools, run scope, context, checkpoints, budgets and output validation. MarkItDown converts PDF/DOCX to Markdown; independent extraction resolves citations to original source positions.

## Run locally with Docker Desktop

1. Install and start Docker Desktop.
2. Copy `.env.example` to `.env`. Set `DEMO_LLM_MODE=fixture` to run without an API key. To use Groq, set `DEMO_LLM_MODE=groq` and provide `GROQ_API_KEY` in `.env`. The key is passed to the backend only. Groq models are configurable per agent with `GROQ_SUPERVISOR_MODEL`, `GROQ_SCIENTIFIC_REVIEW_MODEL`, `GROQ_RELATED_WORK_MODEL` and `GROQ_EVIDENCE_VERIFIER_MODEL`. Before each call, the worker reserves estimated input plus completion tokens in a shared per-model quota window. On a 429 it honors the full `retry-after`; five minutes bounds inline waiting only, and longer waits are saved as a durable cooldown. `GROQ_RATE_LIMIT_WAIT_SECONDS` defaults to `60` when the header is absent or invalid.
3. From the repository root, run:

   ```powershell
   docker compose up --build -d
   docker compose ps
   ```

4. Open [http://localhost:3000](http://localhost:3000). FastAPI docs are at [http://localhost:8000/docs](http://localhost:8000/docs).
5. To load the example library, run:

   ```powershell
   docker compose exec backend python -m app.demo.seed
   ```

   The command can be run again safely. From the browser, open **Bản review**, select `Demo · Evidence Links Pilot`, the `Demo · Scientific Review` rubric and optionally `Demo · Related Study`, then create a draft and run it. Fixture mode labels every report and is only a workflow demonstration.
6. Inspect the actual decisions, skipped agents, tool permissions, contexts, checkpoints, repair attempts and evidence-gate results in the run inspector. When the run completes, open the review and download its Markdown report. Opening a finding's source is optional.
7. Stop the services with `docker compose down`. The `app_data` named volume keeps uploads, database records, run checkpoints and completed reports. `docker compose down -v` also deletes that volume.

Useful commands:

```powershell
docker compose logs -f backend
docker compose restart backend
docker compose up --build -d
```

The app is designed for one local user and one backend worker process. Scanned PDFs without a text layer are rejected; OCR, automatic web search and Literature Review are later extensions. DOCX citations point to paragraphs; PDF citations point to pages.

### Groq quota coordination

`GROQ_TOKENS_PER_MINUTE=8000` and `GROQ_REQUESTS_PER_MINUTE=30` configure the default local rolling 60-second limit for each model. Set these to your account's actual limits, then recreate the backend with `docker compose up -d --build backend`. Supervisor, Comparator and Verifier share the same bucket when configured with the same model. The worker retains its coordinator across turns and runs, even though individual adapters are rebuilt.

Input estimates include prompts, context, schema JSON and chat overhead, using UTF-8 bytes rather than plain character counts. Completion tokens are reserved before sending and reconciled with actual usage afterward. When necessary the completion budget is reduced to fit the window, leaving a 128-token margin and at least 1,024 output tokens (or a role's smaller configured budget). Sources are never cut to fit. Requests that cannot fit this minimum fail with `quota_request_too_large` rather than waiting indefinitely; they need smaller contexts. A smaller completion budget can still yield invalid/incomplete JSON, which remains subject to the adapter's bounded repair and validation.

Trace events `quota_reserved` and `quota_wait` show model, estimated input tokens, reserved output tokens and wait seconds without prompts or credentials. Failed 429 attempts release their token reservation but still count toward local RPM; the provider's deadline blocks all clients sharing that model. A `Retry-After: 381` is never retried after only 300 seconds: it becomes a checkpoint cooldown of 381 seconds.

This is conservative local accounting, not Groq's tokenizer or a guarantee against 429. It resets when the worker process restarts and cannot observe other applications consuming the same organization quota or independently predict daily/input/output-specific limits. Provider responses remain authoritative. Durable run cooldowns survive restart; distributed or multiple-worker deployments require shared persistent quota storage.

Groq reference comparisons process the selected main/reference excerpts in source pairs across checkpointed turns instead of sending four pages together. Every pair retains both papers and all initially selected excerpts are covered across the batches. `comparison_batch_completed` records progress. Runs stopped with `quota_request_too_large` can be resumed with `POST /api/v1/runs/{run_id}/resume` after reducing the oversized context; the original review revision and completed work are retained. This does not guarantee that a single exceptionally large page will fit.

Page and paragraph locators come from the original PDF/DOCX extraction. Markdown formatting differences do not invalidate those original positions. For documents uploaded before this correction, `docker compose exec backend python -m app.services.source_locator_service PAPER_ID VERSION` can reconcile a saved version. The command updates only locators whose chunk text and file hash match the exact original page or paragraph; existing review reports remain unchanged, so start a new review run afterward.

## Project map

```text
backend/app/api/v1/          FastAPI controllers and Pydantic views
backend/app/domain/          Domain models, repository ports and policies
backend/app/services/        CRUD, run orchestration and report export
backend/app/infrastructure/  SQLAlchemy, SQLite, local files, Groq/fixture
backend/app/ingestion/       MarkItDown and original-source locators
backend/app/agents/          Four LangGraph agent contracts and prompts
backend/app/harness/         Loop, state, tools, context, permissions, gate
backend/app/workers/         Single local checkpointed worker
frontend/src/app/            Library, rubric, review and run inspector
demo_data/                   Small generated PDF/DOCX fixture documents
docs/architecture/           MVC/MVT and harness diagrams
docs/api/                     REST resource contract
```

## Development checks

Backend commands (run from repository root):

```powershell
python -m pip install -e "./backend[dev]"
$env:PYTHONPATH = "backend"
pytest backend/tests -q
pylint backend/app --rcfile=backend/pyproject.toml
pycodestyle backend/app backend/tests backend/migrations
```

Frontend commands (run in `frontend/`):

```powershell
npm ci
npm run lint
npm run build
npm run test:e2e
```

Playwright's end-to-end flow needs the fixture backend and Next.js running at ports 8000 and 3000. Start Compose in fixture mode, then run `npm run test:e2e` in another terminal under `frontend/`. No Groq key is required. See [MVC/MVT and patterns](docs/architecture/mvc.md), [harness design](docs/architecture/harness.md), [REST contract](docs/api/rest-contract.md), [approved design](docs/superpowers/specs/2026-10-26-ai-paper-review-design.md) and [step-by-step plan](docs/superpowers/plans/2026-10-26-paper-review-mvp.md).
