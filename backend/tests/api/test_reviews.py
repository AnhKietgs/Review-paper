"""Review draft CRUD, selected reference scope and revisions."""

from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.infrastructure.persistence.database import get_engine
from app.infrastructure.persistence.orm_models import Base, RunRow
from app.main import app
from app.workers.run_worker import RunWorker


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    get_engine.cache_clear()
    Base.metadata.create_all(get_engine())
    yield TestClient(app)
    get_engine().dispose()
    get_engine.cache_clear()


def paper(client: TestClient, title: str) -> str:
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), f"Evidence from {title}.")
    response = client.post(
        "/api/v1/papers",
        data={"title": title},
        files={
            "file": ("paper.pdf", BytesIO(document.tobytes()), "application/pdf"),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def rubric(client: TestClient) -> str:
    response = client.post(
        "/api/v1/rubrics",
        json={
            "name": "General",
            "criteria": [{"code": "method", "question": "Is it sound?"}],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_review_crud_and_revision_snapshot(client: TestClient):
    main_id = paper(client, "main")
    ref_id = paper(client, "reference")
    rubric_id = rubric(client)
    created = client.post(
        "/api/v1/reviews",
        json={
            "paper_id": main_id,
            "rubric_id": rubric_id,
            "reference_paper_ids": [ref_id],
        },
    )
    assert created.status_code == 201, created.text
    review_id = created.json()["id"]
    assert created.headers["location"].endswith(review_id)
    assert created.json()["references"][0]["paper_content_version"] == 1
    assert client.get("/api/v1/reviews").json()["total"] == 1

    changed = client.patch(
        f"/api/v1/reviews/{review_id}",
        json={
            "summary": "Human edited summary",
            "findings": [
                {
                    "criterion_code": "method",
                    "claim": "A specific human note",
                    "evidence": [],
                    "status": "needs_human_review",
                }
            ],
        },
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["findings"][0]["claim"] == "A specific human note"

    updated_doc = pymupdf.open()
    updated_doc.new_page().insert_text((72, 72), "Updated reference evidence.")
    replacement = client.patch(
        f"/api/v1/papers/{ref_id}",
        files={
            "file": ("new.pdf", BytesIO(updated_doc.tobytes()), "application/pdf"),
        },
    )
    assert replacement.status_code == 200
    assert (
        client.get(f"/api/v1/reviews/{review_id}").json()["references"][0][
            "paper_content_version"
        ]
        == 1
    )

    revision = client.post(f"/api/v1/reviews/{review_id}/revisions")
    assert revision.status_code == 201
    assert revision.json()["id"] != review_id
    assert revision.json()["revision"] == 2
    assert revision.json()["parent_revision_id"] == review_id
    assert revision.json()["findings"][0]["claim"] == "A specific human note"
    assert client.get(f"/api/v1/reviews/{review_id}").json()["revision"] == 1
    assert client.delete(f"/api/v1/reviews/{review_id}").status_code == 204
    assert client.get(f"/api/v1/reviews/{review_id}").status_code == 404


def test_findings_follow_frozen_rubric_criterion_order(client: TestClient):
    main_id = paper(client, "ordered review")
    created_rubric = client.post(
        "/api/v1/rubrics",
        json={
            "name": "Ordered criteria",
            "criteria": [
                {"code": "objective", "question": "What is the objective?"},
                {"code": "method", "question": "Is the method sound?"},
                {"code": "limitations", "question": "What are the limitations?"},
            ],
        },
    ).json()
    review = client.post(
        "/api/v1/reviews",
        json={"paper_id": main_id, "rubric_id": created_rubric["id"]},
    ).json()
    updated = client.patch(
        f"/api/v1/reviews/{review['id']}",
        json={
            "findings": [
                {"criterion_code": "limitations", "claim": "Limitation"},
                {"criterion_code": "method", "claim": "Method A"},
                {"criterion_code": "objective", "claim": "Objective"},
                {"criterion_code": "method", "claim": "Method B"},
                {"criterion_code": "other", "claim": "Other note"},
            ]
        },
    )
    assert updated.status_code == 200, updated.text
    assert [item["claim"] for item in updated.json()["findings"]] == [
        "Objective", "Method A", "Method B", "Limitation", "Other note"
    ]

    newer = client.patch(
        f"/api/v1/rubrics/{created_rubric['id']}",
        json={
            "criteria": [
                {"code": "limitations", "question": "Limitations?"},
                {"code": "method", "question": "Method?"},
                {"code": "objective", "question": "Objective?"},
            ]
        },
    )
    assert newer.status_code == 200, newer.text
    fetched = client.get(f"/api/v1/reviews/{review['id']}")
    assert [item["claim"] for item in fetched.json()["findings"]] == [
        "Objective", "Method A", "Method B", "Limitation", "Other note"
    ]


def test_history_latest_run_belongs_to_exact_revision(client: TestClient):
    """History selects the newest run without crossing revision boundaries."""
    draft = client.post(
        "/api/v1/reviews",
        json={"paper_id": paper(client, "history"), "rubric_id": rubric(client)},
    ).json()
    sibling = client.post(
        f"/api/v1/reviews/{draft['id']}/revisions"
    ).json()
    empty = client.get("/api/v1/reviews").json()
    assert all(item["latest_run_id"] is None for item in empty["items"])
    now = datetime.now(timezone.utc)
    run_ids = [str(uuid4()) for _ in range(3)]
    with Session(get_engine()) as session:
        for index, review_id in enumerate(
            [draft["id"], draft["id"], sibling["id"]]
        ):
            session.add(RunRow(
                id=run_ids[index], review_id=review_id,
                requested_review_id=draft["id"], status="completed",
                created_at=now + timedelta(seconds=index),
            ))
        session.commit()
    history = client.get("/api/v1/reviews").json()
    by_id = {item["id"]: item for item in history["items"]}
    assert by_id[draft["id"]]["latest_run_id"] == run_ids[1]
    assert by_id[sibling["id"]]["latest_run_id"] == run_ids[2]
    page = client.get("/api/v1/reviews?limit=1&offset=1").json()
    assert len(page["items"]) == 1
    item = page["items"][0]
    assert item["latest_run_id"] == by_id[item["id"]]["latest_run_id"]
    assert client.get("/api/v1/reviews?offset=100").json()["items"] == []


def test_invalid_reference_selection(client: TestClient):
    main_id = paper(client, "main")
    ref_id = paper(client, "reference")
    rubric_id = rubric(client)
    base = {"paper_id": main_id, "rubric_id": rubric_id}
    assert (
        client.post(
            "/api/v1/reviews",
            json={
                **base,
                "reference_paper_ids": [main_id],
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/reviews",
            json={
                **base,
                "reference_paper_ids": [ref_id, ref_id],
            },
        ).status_code
        == 422
    )
    assert client.delete(f"/api/v1/papers/{ref_id}").status_code == 204
    assert (
        client.post(
            "/api/v1/reviews",
            json={
                **base,
                "reference_paper_ids": [ref_id],
            },
        ).status_code
        == 404
    )


def test_concurrent_revision_forks_get_distinct_monotonic_numbers(client: TestClient):
    main_id = paper(client, "main")
    rubric_id = rubric(client)
    review = client.post(
        "/api/v1/reviews", json={"paper_id": main_id, "rubric_id": rubric_id}
    ).json()
    path = f"/api/v1/reviews/{review['id']}/revisions"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(path), range(2)))
    assert [response.status_code for response in responses] == [201, 201]
    assert sorted(response.json()["revision"] for response in responses) == [2, 3]


def test_delete_unfinished_review_cancels_its_active_run(client: TestClient):
    main_id = paper(client, "unfinished review")
    draft = client.post(
        "/api/v1/reviews",
        json={"paper_id": main_id, "rubric_id": rubric(client)},
    ).json()
    accepted = client.post(f"/api/v1/reviews/{draft['id']}/runs").json()
    worker = RunWorker()
    assert worker.tick()
    assert client.get(f"/api/v1/runs/{accepted['run_id']}").json()["status"] == "running"

    deleted = client.delete(f"/api/v1/reviews/{accepted['review_id']}")

    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/v1/reviews/{accepted['review_id']}").status_code == 404
    run = client.get(f"/api/v1/runs/{accepted['run_id']}").json()
    assert run["status"] == "cancelled"
    assert run["error_code"] == "cancelled_by_user"
    assert worker.tick() is False
