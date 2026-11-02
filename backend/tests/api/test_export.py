"""Export is an automatic deterministic report snapshot with evidence."""

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
