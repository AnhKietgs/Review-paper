"""Whole-paper absence audits are scoped separately from source claims."""

from app.api.v1.schemas.reviews import ReviewRead
from app.services.report_composer import ReportComposer


def test_report_shows_scoped_omission_without_supported_claim_count():
    review = ReviewRead.model_validate({
        "id": "review", "paper_id": "paper", "paper_content_version": 1,
        "rubric_id": "rubric", "rubric_version": 1, "revision": 1,
        "parent_revision_id": None, "status": "completed",
        "analysis": {"coverage": {"processed": 9, "remaining": 0}},
        "summary": "", "reviewer_edits": {}, "references": [],
        "findings": [{
            "id": "o1", "criterion_code": "limitations_ethics",
            "kind": "omission", "claim": (
                "Không tìm thấy thông tin về quy trình đánh giá mô hình "
                "trong văn bản trích xuất v1 sau khi rà soát 9 đoạn."
            ),
            "evidence": [], "status": "not_reported",
            "verdict": "Đã rà soát toàn bộ văn bản trích xuất.",
        }],
    })
    report = ReportComposer().render_markdown(review)
    assert "Thông tin chưa tìm thấy trong toàn văn bản trích xuất" in report
    assert "quy trình đánh giá mô hình" in report
    assert "paper" in report and "v1" in report
    assert "Nhận xét có bằng chứng hỗ trợ: **0**; chưa xác minh: **0**" in report
    assert "Trạng thái: `supported`" not in report
