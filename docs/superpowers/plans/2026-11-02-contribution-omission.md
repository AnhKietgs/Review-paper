# Contribution and Omission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair source-backed contributions and audit whole-paper omissions before publication.

**Architecture:** Extend the Scientific Review output with an omission kind. Keep omission drafts in checkpoint memory until all main chunks are read, then use Evidence Verifier sequentially across bounded chunk groups. Render verified absence with a distinct scoped status.

**Tech Stack:** Python, FastAPI, Pydantic, LangGraph, Next.js, pytest, Pylint, PEP 8.

**Spec:** `docs/superpowers/specs/2026-11-02-contribution-omission.md`

## Global Constraints

- Keep four logical agents and one worker per harness turn.
- Do not claim absence before full main-paper coverage.
- Preserve exact quote and locator validation for positive claims.

## Review Focus

- Missing detail found on a later page must refute the omission.
- Ambiguous audit results must never become `not_reported`.
- An incomplete run must not publish an absence conclusion.
- A bad Contribution quote must receive at most one repair attempt.
- Existing claim and question handling must continue to work.

### Task 1: Harness contracts and coverage audit

- [x] Write failing tests for a contribution quote repair and omission audit outcomes.
- [x] Add omission kind and durable audit cursor; route one bounded audit group per turn to Evidence Verifier.
- [x] Run focused tests, then the full backend suite.

### Task 2: Report and UI

- [x] Write report regression test for `not_reported` and source scope.
- [x] Add a separate report section and distinct UI label for audited omissions.
- [x] Run frontend lint and build.

### Task 3: Local delivery

- [x] Run Pylint and PEP 8 on edited Python modules.
- [x] Rebuild Docker backend/frontend and confirm health.
