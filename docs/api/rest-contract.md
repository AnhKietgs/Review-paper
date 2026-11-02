# REST contract

Base path: `/api/v1`. JSON error body: `{"code":"...","detail":"..."}`. Collections use `{ "items": [], "total": n, "limit": n, "offset": n }`.

| Resource | Methods and routes | Behavior |
| --- | --- | --- |
| Runtime | `GET /health`, `GET /runtime` | Liveness and public fixture/Groq mode |
| Papers | `POST /papers`, `GET /papers`, `GET /papers/{id}`, `PATCH /papers/{id}`, `DELETE /papers/{id}` | Multipart create; JSON metadata update or multipart content replacement; delete is soft |
| Source | `GET /papers/{id}/source?version=n`, `GET /papers/{id}/versions/{n}` | Original upload and converted version snapshot. These frozen routes remain available after soft deletion so old review evidence remains checkable; ordinary `GET /papers/{id}` returns 404. |
| Rubrics | `POST /rubrics`, `GET /rubrics`, `GET /rubrics/{id}`, `PATCH /rubrics/{id}`, `DELETE /rubrics/{id}` | Qualitative criteria; PATCH creates a new immutable criteria version |
| Reviews | `POST /reviews`, `GET /reviews`, `GET /reviews/{id}`, `PATCH /reviews/{id}`, `DELETE /reviews/{id}`, `POST /reviews/{id}/revisions` | Draft CRUD and preserved revisions; main/reference/rubric versions are frozen |
| Runs | `POST /reviews/{id}/runs`, `GET /runs/{id}`, `GET /runs/{id}/events?after=n`, `POST /runs/{id}/resume` | Async accepted run, progress, ordered trace and explicit resume |
| Approval/export | `POST /reviews/{id}/approve`, `GET /reviews/{id}/export.md` | Approval requires a completed run and validated findings; download is the frozen Markdown snapshot |

Expected statuses include `201 Created` for resource creation, `202 Accepted` for queued work, `200 OK` for reads/updates, `204 No Content` for deletion, `404 Not Found` for missing resources, `409 Conflict` for invalid state transitions, and `422 Unprocessable Entity` for invalid input or unsupported document content.

## Run request

`POST /reviews/{id}/runs` accepts `{}` for a full Paper Review or `{ "mode": "verify" }` to verify reviewer edits. A successful response is `{ "run_id": "…", "review_id": "…", "status": "queued" }`; execution occurs on the single local worker. Each request creates a new review revision.

Paper upload is multipart with `file`, `title`, optional `authors` as comma-separated names, `year`, and `doi`. Rubric and review CRUD use JSON matching the OpenAPI schemas at `/openapi.json`.
