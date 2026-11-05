# Source-selected evidence implementation plan

> Execute inline with superpowers:executing-plans. User selected evidence binding by source IDs and text positions.

**Goal:** Scientific Review and Comparator select system-assigned source span IDs; the harness reconstructs exact quotes and locators rather than trusting model-authored quotations.

**Architecture:** Deterministically partition each approved chunk into bounded contiguous spans. Groq producer contexts contain span IDs and their text once, not duplicated raw text. Separate model-facing selection schemas from canonical FindingDraft/EvidenceReference schemas used by persistence, REST and verifier. Resolve selections against the frozen scope and only chunks supplied to that call. Keep old reports and fixture clients compatible. New references retain span_id and Python Unicode code-point start_char/end_char (exclusive end). OutputGate independently rechecks the positions and exact text.

**Approaches:** Direct numeric character offsets from the LLM are fragile, particularly for Vietnamese. Letting it copy quotes retains quote_not_found errors. Preassigned span IDs let it select an exact range without counting or copying. Multiple spans can support a finding; a comparison still needs both papers.

**Constraints:** No invented source/locator IDs, no silent fallback to a different span, no prompt/quote regeneration, no auto-support solely from valid selection. Invalid selections produce an unsupported finding and the existing bounded repair path; omission auditing remains separate. Existing cancelled run stays cancelled. No live Groq calls for validation. No frontend/database migration required because evidence is stored as JSON and locators remain compatible.

- [x] Red/green tests for deterministic Unicode spans, full source coverage, scope/context restrictions, unknown span, unresolved locators, and stored quote/position tampering.
- [x] Implement span builder/resolver and distinct selection output contracts.
- [x] Wire span contexts, model schema selection, and harness resolution for analysis/comparison/repair; retain canonical verifier inputs and legacy evidence support.
- [x] Update producer prompts, exercise complete review/repair/semantic rejection paths with selection fixtures.
- [x] Run backend suite, Pylint and PEP8; independent code review; inspect active runs and rebuild backend; verify image/health without running a real review.

Verification before deployment: 107 backend tests passed (isolated temp directory, HTTP tests with approved local execution), Pylint 10.00/10 and pycodestyle passed on touched Python files. Added REST roundtrip test for quote and position metadata. Active run check: none; fb30146f remains cancelled. No live Groq calls were used.

Deployment verification: TypeScript no-emit check passed. Independent reviewer reported no actionable findings. Docker backend rebuilt and healthy; API health ok. Read-only smoke check against an existing source resolved a 471-character span at [0,471) and passed OutputGate. Cancelled run remains cancelled; zero live model calls made for validation.
