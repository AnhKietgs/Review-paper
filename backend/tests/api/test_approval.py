"""Approval cannot bypass verifier or rewrite approved reports."""

from app.infrastructure.persistence.orm_models import FindingRow
from app.infrastructure.persistence.unit_of_work import UnitOfWork
from app.workers.run_worker import RunWorker


def completed_review(client, draft):
    accepted = client.post(f"/api/v1/reviews/{draft['id']}/runs").json()
    worker = RunWorker()
    for _ in range(20):
        worker.tick()
    return client.get(f"/api/v1/reviews/{accepted['review_id']}").json()


def test_export_keeps_original_provider_mode(api_client, review_seed, monkeypatch):
    review = completed_review(api_client, review_seed(False))
    monkeypatch.setenv("DEMO_LLM_MODE", "groq")
    assert (
        api_client.post(f"/api/v1/reviews/{review['id']}/approve", json={}).status_code
        == 200
    )
    assert (
        "**fixture**"
        in api_client.get(f"/api/v1/reviews/{review['id']}/export.md").text
    )


def test_bad_edited_source_is_rejected_without_failing_run(api_client, review_seed):
    review = completed_review(api_client, review_seed(False))
    revision = api_client.post(
        f"/api/v1/reviews/{review['id']}/revisions"
    ).json()
    revision["findings"][0]["evidence"][0]["chunk_id"] = "outside-run"
    edited = api_client.patch(
        f"/api/v1/reviews/{revision['id']}",
        json={"findings": revision["findings"]},
    )
    assert edited.status_code == 200, edited.text
    accepted = api_client.post(
        f"/api/v1/reviews/{revision['id']}/runs", json={"mode": "verify"}
    ).json()
    for _ in range(15):
        RunWorker().tick()
    assert (
        api_client.get(f"/api/v1/runs/{accepted['run_id']}").json()["status"]
        == "completed"
    )
    result = api_client.get(f"/api/v1/reviews/{accepted['review_id']}").json()
    assert result["status"] == "completed"
    assert result["findings"][0]["status"] == "supported"
    assert result["findings"][0]["evidence"][0]["chunk_id"] != "outside-run"


def test_edit_requires_verification_and_approved_revision_is_locked(
    api_client, review_seed
):
    review = completed_review(api_client, review_seed())
    assert review["status"] == "completed"
    assert api_client.patch(
        f"/api/v1/reviews/{review['id']}", json={"summary": "overwrite"}
    ).status_code == 409
    revision = api_client.post(
        f"/api/v1/reviews/{review['id']}/revisions"
    ).json()
    findings = revision["findings"]
    findings[0]["claim"] = "Human clarified observation"
    edited = api_client.patch(
        f"/api/v1/reviews/{revision['id']}", json={"findings": findings}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["findings"][0]["status"] == "pending"
    approval = api_client.post(
        f"/api/v1/reviews/{revision['id']}/approve", json={}
    )
    assert approval.status_code == 409
    accepted = api_client.post(
        f"/api/v1/reviews/{revision['id']}/runs", json={"mode": "verify"}
    ).json()
    for _ in range(15):
        RunWorker().tick()
    new_id = accepted["review_id"]
    assert api_client.get(f"/api/v1/reviews/{new_id}").json()["status"] == "completed"
    assert (
        api_client.patch(
            f"/api/v1/reviews/{new_id}", json={"summary": "overwrite"}
        ).status_code
        == 409
    )
    original_revision = api_client.get(f"/api/v1/reviews/{revision['id']}")
    assert original_revision.json()["status"] == "draft"


def test_unsupported_blocks_and_human_confirmation_keeps_uncertain_label(
    api_client, review_seed
):
    review = completed_review(api_client, review_seed(False))
    finding_id = review["findings"][0]["id"]
    with UnitOfWork() as unit:
        unit.session.get(FindingRow, finding_id).status = "unsupported"
    assert (
        api_client.post(
            f"/api/v1/reviews/{review['id']}/approve",
            json={"confirmations": [finding_id]},
        ).status_code
        == 409
    )
    with UnitOfWork() as unit:
        unit.session.get(FindingRow, finding_id).status = "needs_human_review"
    assert (
        api_client.post(f"/api/v1/reviews/{review['id']}/approve", json={}).status_code
        == 409
    )
    approved = api_client.post(
        f"/api/v1/reviews/{review['id']}/approve", json={"confirmations": [finding_id]}
    )
    assert approved.status_code == 200
    assert approved.json()["findings"][0]["status"] == "needs_human_review"
