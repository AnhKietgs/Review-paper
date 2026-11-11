"""Reproducible demo uses the real conversion and harness paths."""

import json
from pathlib import Path

from app.demo.seed import main, seed
from app.infrastructure.persistence.unit_of_work import UnitOfWork
from app.workers.run_worker import RunWorker


def test_seed_twice_and_full_fixture_review(api_client):
    assets = Path(__file__).resolve().parents[3] / "demo_data"
    with UnitOfWork() as unit:
        first = seed(unit.session, assets)
    with UnitOfWork() as unit:
        assert seed(unit.session, assets) == first
    assert api_client.get("/api/v1/papers").json()["total"] == 2
    assert api_client.get("/api/v1/rubrics").json()["total"] == 1
    library = json.loads((assets / "library.json").read_text(encoding="utf-8-sig"))
    stored = api_client.get(f"/api/v1/rubrics/{first['rubric_id']}").json()
    assert stored["name"] == library["rubrics"][0]["name"]
    assert [item["code"] for item in stored["criteria"]] == [
        item["code"] for item in library["rubrics"][0]["criteria"]
    ]
    draft = api_client.post("/api/v1/reviews", json=first).json()
    run = api_client.post(f"/api/v1/reviews/{draft['id']}/runs").json()
    worker = RunWorker()
    for _ in range(50):
        worker.tick()
    result = api_client.get(f"/api/v1/runs/{run['run_id']}").json()
    assert result["status"] == "completed"
    review = api_client.get(f"/api/v1/reviews/{run['review_id']}").json()
    comparisons = [f for f in review["findings"] if f["kind"] == "comparison"]
    assert comparisons
    assert all(len({e["paper_id"] for e in f["evidence"]}) == 2 for f in comparisons)
    assert review["status"] == "completed"
    export = api_client.get(f"/api/v1/reviews/{run['review_id']}/export.md")
    assert "fixture" in export.text


def test_automatic_import_preserves_existing_library(api_client, monkeypatch):
    """Restarting must not restore removed sample records or replace edits."""
    assets = Path(__file__).resolve().parents[3] / "demo_data"
    with UnitOfWork() as unit:
        first = seed(unit.session, assets)
    changed = api_client.patch(
        f"/api/v1/rubrics/{first['rubric_id']}", json={"name": "Local edited rubric"}
    )
    assert changed.status_code == 200
    monkeypatch.setattr("sys.argv", ["seed", "--if-empty"])
    main()
    assert api_client.get("/api/v1/rubrics").json()["total"] == 1
    assert api_client.get(
        f"/api/v1/rubrics/{first['rubric_id']}"
    ).json()["name"] == "Local edited rubric"


def test_automatic_import_loads_empty_library(api_client, monkeypatch):
    """A fresh database gets the shared sources and rubric on first boot."""
    monkeypatch.setattr("sys.argv", ["seed", "--if-empty"])
    main()
    main()
    assert api_client.get("/api/v1/papers").json()["total"] == 2
    assert api_client.get("/api/v1/rubrics").json()["total"] == 1
