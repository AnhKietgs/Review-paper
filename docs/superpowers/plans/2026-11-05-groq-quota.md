# Shared Groq quota implementation plan

> Execute inline with superpowers:executing-plans; the user selected proactive quota management.

**Goal:** Estimate input plus reserved completion tokens before Groq requests, coordinate all agents, and honor Retry-After without early retries.

**Architecture:** One thread-safe coordinator per local worker, with rolling 60-second token/request reservations per model. Clients survive logically through the shared coordinator even when rebuilt each turn. Reconcile reservations with actual usage; rejected 429 calls release token reservations and impose a model-wide provider deadline. The coordinator is local to one process; it cannot account for other applications using the same organization quota.

**Approach:** Use the existing single worker and in-memory accounting. Redis/multiple workers would add deployment scope; separate per-agent counters cannot coordinate the three agents sharing 20B. No tokenizer/model downloads: estimate UTF-8 text size conservatively, including schema and message overhead, and reserve max_completion_tokens. Estimates cannot guarantee zero 429s.

**Constraints:** Preserve FastAPI service/adapter boundaries, existing model routing, exact evidence, Groq credentials privacy, and Pylint/PEP8. Defaults: 8,000 TPM and 30 RPM per model, configurable. A request exceeding an entire window fails explicitly rather than waiting forever or truncating sources. Five minutes bounds inline waiting; a longer provider deadline is persisted as cooldown, never shortened. No new review is started for verification.

- [x] Add clock-controlled quota regression tests: shared model, independent models, rolling expiry, concurrent reservations, actual usage reconciliation, oversized request, and provider cooldown.
- [x] Implement estimator and coordinator in infrastructure/groq/quota.py.
- [x] Test and integrate client reservations including JSON repair/retry. Preserve the complete Retry-After in durable pauses; trace quota estimates/waits without prompts or keys.
- [x] Wire one coordinator into RunWorker across clients and turns; add environment defaults and README explanation.
- [x] Run relevant tests and lint; inspect active runs, rebuild backend and verify health/image. Report estimates and single-process limitations.

Ruling: reserve a smaller completion budget when a source context can fit with at least min(1,024, configured output budget) output tokens plus a 128-token margin. Real stored contexts can exceed 8K when paired with the old fixed 4,096 output budget. Do not truncate evidence. If even the minimum cannot fit, fail explicitly; a separate context batching improvement is needed.

Verification: 86 backend tests passed with an isolated temporary directory, including short 429 recovery and durable 381-second cooldown. Pylint 10.00/10 and pycodestyle passed on modified Python files. Docker rebuilt, API health ok, backend healthy. No active runs existed before rebuild; no live model requests were made for verification. A separate code reviewer found no actionable correctness/regression issues; the two suggested coverage gaps were added as regression tests. The default restricted environment cannot reliably run HTTP test threads, so the full suite ran with the existing approved test permission.

## Follow-up: oversized comparison context

Live failure fb30146f-a5c6-4bec-bcd6-4f7bf820749f stopped on comparison at turn 39 after 9 main-paper chunks and 29 findings. Four source excerpts produced 8,162 estimated input tokens before output. Added checkpointed comparison_progress to split the previously selected excerpts into main/reference pairs, one per turn; fixture mode retains its earlier behavior. Actual checkpoint dry run produced input estimates 4,573 and 5,278; remaining omission source groups also fit. Resume permits this quota error after the context fix, retaining the same run/revision. Reviewer identified unavailable references between batches; added an availability check and regression test to mark not_assessed rather than failing the run.
