"""Reproducible demo uses the real conversion and harness paths."""

from pathlib import Path

from app.demo.seed import seed
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
