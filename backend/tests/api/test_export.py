"""Export is an automatic deterministic report snapshot with evidence."""

import json

from app.agents.schemas import ScientificOutput, VerificationOutput
from app.infrastructure.groq.fixture_client import FixtureClient
from app.workers.run_worker import RunWorker


def test_completed_run_exports_without_human_approval(api_client, review_seed):
    draft = review_seed()
    assert api_client.get(f"/api/v1/reviews/{draft['id']}/export.md").status_code == 409
    accepted = api_client.post(f"/api/v1/reviews/{draft['id']}/runs").json()
    for _ in range(20):
        RunWorker().tick()
    review_id = accepted["review_id"]
    completed = api_client.get(f"/api/v1/reviews/{review_id}")
    assert completed.json()["status"] == "completed"
    report = api_client.get(f"/api/v1/reviews/{review_id}/export.md")
    assert report.status_code == 200
    for section in (
        "Mục tiêu",
        "Phương pháp",
        "Kết quả",
        "Đóng góp",
        "Điểm mạnh",
        "Hạn chế",
        "So sánh",
        "Câu hỏi",
        "Giới hạn",
        "PDF",
    ):
        assert section in report.text
    assert "24 participants" in report.text
    assert "40 participants" in report.text
    assert (
        report.content
        == api_client.get(f"/api/v1/reviews/{review_id}/export.md").content
    )


def test_omission_export_uses_full_document_scope(
    api_client, review_seed, monkeypatch
):
    class OmissionClient(FixtureClient):
        def generate_json(self, messages, schema):
            result = super().generate_json(messages, schema)
            context = json.loads(messages[-1]["content"])
            if schema is ScientificOutput:
                result.findings[0].kind = "omission"
                result.findings[0].claim = "quy trình tuyển chọn người tham gia"
                result.findings[0].evidence = []
            if schema is VerificationOutput and context.get("omission_audit"):
                result.assessments[0].status = "unsupported"
            return result

    monkeypatch.setattr("app.workers.run_worker.FixtureClient", OmissionClient)
    draft = review_seed(with_reference=False)
    accepted = api_client.post(f"/api/v1/reviews/{draft['id']}/runs").json()
    for _ in range(20):
        RunWorker().tick()
    review = api_client.get(f"/api/v1/reviews/{accepted['review_id']}").json()
    assert review["status"] == "completed"
    assert review["findings"][0]["status"] == "not_reported"
    report = api_client.get(
        f"/api/v1/reviews/{accepted['review_id']}/export.md"
    )
    assert report.status_code == 200
    assert "Thông tin chưa tìm thấy trong toàn văn bản trích xuất" in report.text
