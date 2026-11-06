export interface Page<T> { items: T[]; total: number; limit: number; offset: number }
export interface Locator { type: string; value: string; status: string; quote?: string }
export interface Chunk { id: string; text: string; content_version: number; locator: Locator | null }
export interface Paper {
  id: string; title: string; authors: string[]; year: number | null; doi: string | null;
  original_filename: string; media_type: string; content_version: number;
  conversion_status: string; markdown: string; chunks: Chunk[];
}
export interface Criterion { code: string; question: string; guidance: string; order_index?: number }
export interface Rubric { id: string; name: string; description: string; version: number; criteria: Criterion[] }
export interface Evidence {
  paper_id: string; content_version: number; chunk_id: string; quote: string;
  locator_type: string; locator_value: string;
  span_id?: string | null; start_char?: number | null; end_char?: number | null;
}
export interface Finding {
  id: string; criterion_code: string; kind: string; claim: string; evidence: Evidence[];
  status: string; verdict: string; compared_paper_ids: string[];
}
export interface Review {
  id: string; paper_id: string; paper_content_version: number; rubric_id: string;
  rubric_version: number; revision: number; parent_revision_id: string | null;
  status: string; summary: string; analysis: Record<string, unknown>;
  reviewer_edits: Record<string, unknown>;
  references: { paper_id: string; paper_content_version: number }[]; findings: Finding[];
}
export interface AcceptedRun { run_id: string; review_id: string; status: string }
export interface RunActivity {
  phase: string; resume_action: string | null; agent: string | null;
  source: "live" | "checkpoint"; updated_at: string | null; retry_at: string | null;
  work: {
    token_tasks?: { done: number; total: number };
    paper_read: { done: number; total: number };
    references: { done: number; total: number };
    findings: { total: number; pending_verification: number; pending_repairs: number; repair_attempts: number };
    omission_audit: { topics_pending: number; group_topics: number; checked_chunks: number; total_chunks: number };
  };
}
export interface Run {
  id: string; review_id: string; status: string; step_count: number;
  batch_count: number; processed: number; remaining: number; max_batches: number;
  max_turns: number; error_code: string | null; cooldown_until: string | null;
  call_counts: Record<string, number>;
  usage: { calls?: number; tokens?: number };
  reference_assessments: Record<string, { status: string; reason: string }>;
  activity?: RunActivity;
}
export interface RunEvent {
  id: string; sequence: number; agent: string; action: string; tool: string | null;
  permission_result: string | null; input_summary: string; output_summary: string;
  payload: Record<string, unknown>; timestamp: string;
}
