# REST contract

Base path: `/api/v1`. JSON error body: `{"code":"...","detail":"..."}`. Collections use `{ "items": [], "total": n, "limit": n, "offset": n }`.

| Resource | Methods and routes | Behavior |
| --- | --- | --- |
| Runtime | `GET /health`, `GET /runtime` | Liveness and public fixture/Groq mode |
| Papers | `POST /papers`, `GET /papers`, `GET /papers/{id}`, `PATCH /papers/{id}`, `DELETE /papers/{id}` | Multipart create; JSON metadata update or multipart content replacement; delete is soft |
| Source | `GET /papers/{id}/source?version=n`, `GET /papers/{id}/versions/{n}` | Original upload and converted version snapshot. These frozen routes remain available after soft deletion so old review evidence remains checkable; ordinary `GET /papers/{id}` returns 404. |
| Rubrics | `POST /rubrics`, `GET /rubrics`, `GET /rubrics/{id}`, `PATCH /rubrics/{id}`, `DELETE /rubrics/{id}` | Qualitative criteria; PATCH creates a new immutable criteria version |
| Reviews | `POST /reviews`, `GET /reviews`, `GET /reviews/{id}`, `PATCH /reviews/{id}`, `DELETE /reviews/{id}`, `POST /reviews/{id}/revisions` | Draft CRUD and preserved revisions; main/reference/rubric versions are frozen |
| Runs | `POST /reviews/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/events?after=n`, `POST /runs/{id}/resume`, `POST /runs/{id}/cancel` | Async accepted run, progress, ordered trace, explicit resume and cancellation |
| Approval/export | `POST /reviews/{id}/approve`, `GET /reviews/{id}/export.md` | Approval requires a completed run and validated findings; download is the frozen Markdown snapshot |

Expected statuses include `201 Created` for resource creation, `202 Accepted` for queued work, `200 OK` for reads/updates, `204 No Content` for deletion, `404 Not Found` for missing resources, `409 Conflict` for invalid state transitions, and `422 Unprocessable Entity` for invalid input or unsupported document content.

## Run request

`POST /reviews/{id}/runs` accepts `{}` for a full Paper Review or `{ "mode": "verify" }` to verify reviewer edits. A successful response is `{ "run_id": "…", "review_id": "…", "status": "queued" }`; execution occurs on the single local worker. Each request creates a new review revision.

Paper upload is multipart with `file`, `title`, optional `authors` as comma-separated names, `year`, and `doi`. Rubric and review CRUD use JSON matching the OpenAPI schemas at `/openapi.json`.

`POST /runs/{id}/cancel` returns `200` with the run/review IDs and status
`cancelled`. It accepts queued, running, interrupted or failed runs and is
idempotent for cancelled runs. Completed/incomplete runs return `409`; unknown
runs return `404`. It retains the review, findings and checkpoint, clears any
quota cooldown and prevents resume of the cancelled run. A new run may be created
separately. Cancellation and final result persistence are serialized so late
results cannot overwrite cancellation. Groq attempts check cancellation before
requests and during quota waits; a request already sent cannot be revoked, but
its late result is not applied after cancellation.

`POST /runs/{id}/resume` accepts interrupted runs and recoverable failed runs
(`rate_limited`, `quota_request_too_large`, `provider_unavailable`,
`provider_timeout`, `provider_connection_error`). It queues the same run and
revision, retaining the chosen action, split contexts and completed subcall
outputs. It does not restart successful work or automatically resume failures.
Permanent authentication, model and input errors require correcting the cause.
