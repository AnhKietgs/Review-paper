# Paper Review harness

```mermaid
flowchart TD
  Queue[Document queue] --> State[RunState checkpoint]
  State --> Supervisor[Supervisor Agent]
  Supervisor --> Guard{Harness checks action and budget}
  Guard -->|next_batch| Queue
  Guard -->|analyze| Tools[Tool Gateway]
  Guard -->|compare selected reference| Tools
  Guard -->|verify pending findings| Tools
  Tools --> Permission{Role allowlist and frozen scope}
  Permission -->|allow| Context[Bounded role context]
  Permission -->|deny| Trace[Persist denial event]
  Context --> Worker[One LangGraph worker]
  Worker --> Consolidate[Consolidate exact-content findings]
  Consolidate --> Gate[Deterministic provenance gate]
  Gate -->|valid evidence| Pending[Pending findings]
  Pending --> Supervisor
  Gate -->|bad source or quote| Unsupported[Unsupported finding]
  Worker --> Assessment[Reference assessments]
  Assessment --> Supervisor
  Supervisor -->|finish| Complete[Completed or incomplete]
  State --> Memory[(SQLite checkpoint)]
  Guard --> Trace
  Gate --> Trace
  Complete --> Trace
```

## Harness capabilities

| Capability | Implementation | Visible trace |
| --- | --- | --- |
| Loop | Supervisor action per turn, 20 document batches and 80 turns by default | Decision, batch selection, budget exhausted |
| Tool | `read_chunks`, `search_reference`, `read_rubric` | Tool name, safe source IDs and result |
| Memory | Versioned `RunState` persisted after each turn | Checkpoint event, processed and remaining counts |
| Context | Constructed from permitted tool results, selected rubric and public progress | Context event and included source IDs |
| Permission | Agent allowlist and frozen paper/version scope before data is returned | Allow or deny result |
| Output control | Strict schemas, source identity/version, exact nonempty quote, resolved locator and comparison coverage | Per-finding validation result and reason codes |
| Agent activation | One worker per supervisor turn; comparator only for selected papers; verifier only for pending evidence | Call counts and `agent_skipped` events |
| Finding consolidation | Same criterion, kind, compared-paper set and normalized claim; union provenance-valid evidence under the first canonical ID | `findings_merged`, canonical/merged IDs, added evidence and verification state |

Supervisor is the control agent; the other three are subagents called through the harness. A worker never receives a Groq key, opens a file, or runs a tool directly. In fixture mode, generated output is clearly labeled as a workflow example. In Groq mode, provider JSON structure is checked locally and source provenance is checked independently; a valid quote still does not prove scientific correctness.

For PDF, a locator is a one-based page. For DOCX, it is a one-based nonempty paragraph index. MarkItDown supplies Markdown for model context; independent original-file extraction anchors citations. If conversion text does not map uniquely, the locator stays unresolved and the output gate prevents it from being marked supported.

The run inspector renders persisted events; its diagram reflects actual call counts. It does not invent intermediate agent activity. Failed runs can be inspected, while interrupted runs can be explicitly resumed from their saved state.

Provider recovery distinguishes timeout, connection, authentication, missing model,
invalid request and temporary HTTP failures. Timeout/connection/408/409/5xx may
retry twice per structured generation with 2/4-second backoff, respecting numeric
or HTTP-date Retry-After. A delay above 30 seconds stops inline recovery; the run
retains its checkpoint for explicit resume. Quota handling remains separate and
can add its own wait. Cancellation is checked during backoff. Trace records only
safe failure type, status, request ID and retry decision, never raw response
bodies, prompts or credentials. Legacy provider_unavailable traces cannot reveal
the historical upstream cause that the old adapter discarded.

## Consolidation before verification

The harness consolidates drafts before adding verification or repair work. Claim
identity uses NFC Unicode normalization, case folding and whitespace collapse;
punctuation, numbers, negation and accents remain significant. Criterion codes,
finding kinds and sets of compared paper IDs must match exactly. Paraphrases and
translations are deliberately not merged, and this step makes no model calls.

The first finding keeps its ID and wording. Only source references passing the
provenance gate enter the evidence union; comparison findings still require both
sides before reaching Evidence Verifier. Duplicate source references, including
extraction whitespace differences in legacy quotes, do not reopen a final verdict.
New valid evidence clears the old verdict and queues the canonical claim for fresh
semantic verification. Restored mixed-quality source lists are sanitized before
verification. Partial valid comparison sources can accumulate while the finding
remains unsupported, rather than being discarded.

Pending queues are consolidated again before verification, covering checkpoint
resume and repaired drafts. Duplicate repair jobs share the canonical ID and the
existing bounded repair attempt; a repair matching another verified claim can skip
verification. Omission topics are grouped without resetting full-paper audit
progress. Merge decisions appear in the normal trace and the resulting lists are
saved through the existing checkpoint. No completed historical reviews are migrated.

Consolidation reduces repeated claims and verification input size. It reduces the
number of verifier calls when a repeated claim has no new evidence; claims that
gain genuinely new sources are verified again, so call savings depend on the run.

## Continuing an unfinished turn after quota cooldown

`RunState.turn_progress` stores the accepted Supervisor action, prepared worker
context and any successfully received worker output for one unfinished turn.
After a worker hits a quota limit, the background worker persists the latest safe
checkpoint and cooldown deadline, instead of discarding the Supervisor decision.
The next tick restores that action, rechecks scheduling eligibility, and retries
only the unfinished worker. A retry remains in the same logical turn, including
when that turn reached the configured turn budget.

The saved domain state stays at the pre-worker boundary: a throttled repair does
not lose its queue entry or spend a repair attempt, an omission audit does not
advance its cursor, and an analysis does not duplicate findings or coverage.
Actual worker-call counters still include retried calls. Prepared context is
reused only while source permissions, versions and content still match; ordinary
output validation remains mandatory. Successfully received structured output can
be reused during replay without a second model call. Progress is cleared only
when the action completes or the scheduling guard rejects it.

Trace events `decision_reused`, `context_reused` and `worker_output_reused` expose
reuse. `provider_cooldown` includes `resume_action`. Old checkpoints without
`turn_progress` continue normally. SQLite receives the intermediate checkpoint at
the tick's persistence boundary, including quota/failure exits; model calls do not
hold a SQLite write transaction. A hard process crash before that boundary, or a
provider response lost before reception, cannot guarantee exactly-once model calls.

## Actual work progress in the run inspector

GET `/api/v1/runs/{id}` includes a safe `activity` projection: current phase,
agent, resume action, optional retry deadline, and measured work counts. While a
single local worker is inside a provider call, event callbacks publish thread-safe
in-process metadata so HTTP readers do not have to wait for the tick to finish.
No document text, model context or raw output is included in this projection.
Live metadata is cleared on every tick exit. Lifecycle states and future persisted
cooldowns override live data; after a cooldown expires, an actual resumed worker
can replace the stale waiting phase. Checkpoint data is the fallback after restart
or between ticks. This live channel assumes the existing single-process backend;
multiple API processes would need a shared activity store.

The UI names planning, analysis, comparison, verification, repair, omission audit,
finalization and quota waits. The progress bar measures main-paper reading only;
reading all chunks does not imply completion of verification or the whole review.
Separate counters show pending verification/repairs, executed repair attempts,
processed references and checked chunks for the current omission-topic group.
The interface shows whether data is live or checkpoint-based and reports polling
freshness/connection failures. Countdown means the next retry time, never an ETA
for the complete review. Navigation stays available throughout.

## Work sized by request tokens

Source pages/paragraphs remain immutable coverage and location records. Before a
Groq worker call, the runtime planner checks the exact role prompt, context and
JSON schema with the same UTF-8 token estimator used by the adapter. It reserves
the configured full completion budget plus 256 tokens for framing/schema-repair
headroom against the configured per-model token window. Estimates are heuristic;
provider 429 handling remains necessary.

Long producer inputs are partitioned and greedily packed using original span IDs.
No chunk is replaced or renumbered; the evidence resolver still derives exact
quotes and absolute Unicode character offsets from the original chunk. Comparison
work keeps both main and related sources, reusing an anchor when needed. Retrieval
scope itself is unchanged by partitioning.

Verification is packed by finding groups with all cited spans and nearby context,
not all full source pages. When necessary, nearby context is reduced before any
cited passage; cited evidence is never discarded to manufacture a fit.
When a single finding has too many citations, its evidence is partitioned too,
preserving both sides in every comparison assessment. The original finding keeps
all of its evidence; inconsistent subset assessments produce uncertainty rather
than a supported claim.
Omission audits group topics against every assigned source span and overlap boundary spans
when capacity permits. Presence in any window refutes absence. Missing/ambiguous
assessments, or a budget too small to retain boundary context, produce uncertainty
rather than a whole-document absence claim.

`TurnProgress.work_contexts` and `work_outputs` retain completed subcalls. Quota
resume starts at the unfinished subcall without a new Supervisor decision. Domain
findings and page coverage are advanced only after the work is combined. These
fields use the existing tick-boundary persistence guarantees described above.
The inspector exposes completed/total subtask counts through metadata, with
`token_work_planned`, `token_work_started` and `token_work_completed` trace events.

An indivisible claim or fixed rubric/prompt/schema that cannot fit even with the
minimum source unit fails with `token_work_item_too_large`. It is not treated as a
temporary quota shortage and is not retried indefinitely. Large metadata is not
silently truncated. In-flight cached work assumes unchanged prompt/model/budget
configuration; changing those during a paused run may require a new revision.

## Review token economy

New runs snapshot `REVIEW_TOKEN_BUDGET` (default50,000 across all models) and
`REVIEW_FINDINGS_PER_CRITERION` (default4). Each HTTP attempt reserves estimated
input plus the output allowance before sending; retries and JSON repairs share
the ledger. Reported usage reconciles successful requests; unknown usage remains
conservatively charged and confirmed429 rejection releases the charge. At least
the recorded run usage is restored for legacy runs. State preserves spending at
the existing turn transaction boundary, including failure/cooldown. A hard
process termination midturn can lose that turn's local accounting: this is an
application admission guard, not an exact billing ledger or the organization's
remaining daily quota.

When the next request cannot fit, execution stops as `incomplete` with
`review_token_budget_exhausted`, retaining pending work and completed subcall
outputs. It is not automatically retried, frozen as a completed report or
resumable through the ordinary endpoint. Changing environment settings affects
new runs, not an existing run's frozen allowance. Starting a new revision spends
a new budget and does not restore Groq daily quota.
Startup recovery also ends legacy running/cooldown runs whose recorded spending
already reaches the run allowance, before honoring an old quota deadline. It
retains the saved work and sends no request to resume that depleted run.

Producers receive remaining finding slots. Staging rejects codes outside the
frozen rubric, merges duplicate claims before counting pending/final/omission
findings, and skips extra unique drafts with a trace event. The first admitted
drafts are retained; this does not rank all possible observations by importance.
All assigned document text is still read. Reviewer-entered verify-only findings
are retained. Verifier uses the same ID/status/reason contract with short reasons,
at most4 topics/findings per work item and a2,048-token output allowance. Exact
evidence, omission coverage and conservative uncertain judgments remain intact.

## Compact review policy

New Groq runs enable `efficient_review`: read the assigned main document, compare
selected references, verify consolidated findings, then perform bounded repairs
and omission audits. Existing pending/finished findings share the same criterion
limit. One initial Supervisor model decision is retained; subsequent sole legal
actions use `decision_shortcut` without an HTTP call. Ambiguous reference choices
still use the model. This is a controller optimization, not invented model calls.
Fixture defaults retain the prior schedule; explicit optimized-policy tests compare
the resulting claims/statuses/source unions against that baseline.

Existing Groq runs adopt this policy only at a clean worker turn boundary.
Admitted actions, contexts and successful split outputs finish under their saved
policy first. Batch/turn/token limits, cancellation, missing source handling and
the output gate remain enforced; no budget is raised or reset.

For selection-capable clients, Verifier transport projects canonical inputs to
claims, evidence chunk/span links, source identities and source text presented
once. Legacy references without span IDs retain exact quotes. Omission mode and
all assigned span text are preserved. Permissions, locator and character-offset
checks remain in the harness; model transport never mutates canonical data.
Planner and sender share this projection and compact JSON/schema serialization.
The inspector explains deferred verification with an economy-policy hint.

On the synthetic four-claim benchmark, estimated complete request input fell
from5,168 to1,999 tokens (61.3%). This is a reproducible offline transport estimate,
not a measured Groq billing reduction or a guarantee a paper fits50,000 tokens.

## Two-phase Scientific Review

New full Groq runs snapshot `two_phase_review=true`. Reading (`analyze` action,
`extract` activity) uses `GROQ_SCIENTIFIC_EXTRACTION_MODEL`, default20B,1536output
tokens and low reasoning for supported GPT-OSS models. It returns up to6 factual
notes, each at most160characters and2source selections. The harness resolves
quotes/versions/locators/absolute character positions from original spans, rejects
unknown criteria/bad sources and checkpoints successful reading subcalls. Notes
are unverified inputs, never scientific findings or proof of document-wide absence.

Once all main text is read, `synthesize` invokes the same logical Scientific Review
agent on120B with2048output tokens. Token packing groups notes with original cited
source spans and neighboring context; model-facing notes use source links rather
than duplicate quotes. All notes are assigned work, and indivisible over-budget
items fail safely. Normal resolver, criterion cap, provenance gate and Evidence
Verifier still apply to generated findings. Source IDs and original offsets are
unchanged. Partial successful synthesis outputs are reused after quota waits.

Internal extraction/synthesis client adapters share the existing model quota and
run token ledger with all other roles; they are not additional logical agents.
Trace records phase/model under scientific_review and the UI shows extraction,
note count and synthesis separately. Legacy and verification-only runs keep their
saved workflow; they are never silently reread to create missing notes.

New mode limits repairs to2attempts, skips optional question repair, and admits
at most2specific omission topics. Omission audits still scan original main-paper
text with full coverage and conservative uncertainty. No absence conclusion comes
from notes alone. If no valid notes exist, scientific synthesis stops incomplete
with scientific_notes_unavailable rather than completing an empty review.
Reports disclose selected-note/source scope and bounded repair/omission policy.

The synthetic9-chunk benchmark reserves59,625tokens for old per-chunk scientific
analysis versus35,604reading+10,999synthesis=46,603 (21.8%lower). Strong-model tasks
fall9→2; input estimates include prompts/schema. This excludes other roles and is
not billed usage, a scientific quality evaluation or a70k completion guarantee.
GPT-OSS reasoning settings are documented by
[Groq](https://console.groq.com/docs/reasoning).
