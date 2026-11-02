# Run Navigation Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep users on the live inspector while a paper review is queued or running and make the running state visibly active.

**Architecture:** Expose one read-only active-run endpoint backed by persisted run rows. The root shell polls it, disables in-app navigation and redirects other app routes to the active inspector. The inspector presents an animated running badge and re-enables navigation when the run reaches a terminal state.

**Tech Stack:** FastAPI, SQLAlchemy, Next.js, React, CSS, pytest, Playwright.

**Spec:** User confirmed “tab khác” means the app's navigation items, not browser tabs.

## Global Constraints

- Lock only while a run is `queued` or `running`.
- Keep the inspector accessible while locked.
- Respect `prefers-reduced-motion`.
- Do not block browser controls or other browser tabs.

## Review Focus

- Direct navigation and browser Back during a running review return to the active inspector.
- A refresh while running restores the lock from backend state.
- Completed or failed runs unlock navigation automatically.
- Temporary API failure does not accidentally unlock an already known active run.
- The status animation is readable without motion.

### Task 1: Active-run API

- [x] Add a failing API test for no active run, queued/running run, and completed run.
- [x] Add the read-only service query and route before dynamic run routes.
- [x] Run focused backend tests.

### Task 2: Locked app navigation and live status

- [x] Add shell polling, immediate lock on run creation, locked navigation, and route guard.
- [x] Animate the running badge and respect reduced motion.
- [x] Verify responsive styling, lint, build, and a browser flow.

### Task 3: Local delivery

- [x] Run backend suite, Pylint, PEP 8, frontend checks.
- [x] Rebuild local Docker services and confirm health.
