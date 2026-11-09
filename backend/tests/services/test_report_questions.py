"""Author questions are sourced prompts, not scientific conclusions."""

from app.api.v1.schemas.reviews import ReviewRead
from app.services.report_composer import ReportComposer


def test_report_discloses_selected_note_scope_and_no_valid_note_case():
    review = ReviewRead.model_validate({
        "id": "review", "paper_id": "paper", "paper_content_version": 1,
        "rubric_id": "rubric", "rubric_version": 1, "revision": 1,
        "parent_revision_id": None, "status": "completed", "analysis": {
            "workflow": {"two_phase_review": True, "note_count": 0,
                         "max_repairs": 2, "max_omission_topics": 2},
        }, "summary": "", "reviewer_edits": {}, "references": [], "findings": [],
    })
    report = ReportComposer().render_markdown(review)
    assert "ghi chú và đoạn nguồn được chọn" in report
    assert "chưa được đánh giá" in report


def test_report_separates_grounded_questions_and_omits_ungrounded_ones():
    source = {
        "paper_id": "paper",
        "content_version": 1,
        "chunk_id": "chunk",
        "quote": "The sample contains 24 participants.",
        "locator_type": "pdf_page",
        "locator_value": "2",
    }
    review = ReviewRead.model_validate({
        "id": "review", "paper_id": "paper", "paper_content_version": 1,
        "rubric_id": "rubric", "rubric_version": 1, "revision": 1,
        "parent_revision_id": None, "status": "completed", "analysis": {},
        "summary": "", "reviewer_edits": {}, "references": [],
        "findings": [
            {"id": "q1", "criterion_code": "method", "kind": "question",
             "claim": "How were participants recruited?", "evidence": [source],
             "status": "grounded", "verdict": "Source names sample size."},
            {"id": "q2", "criterion_code": "method", "kind": "question",
             "claim": "Was funding disclosed?", "evidence": [],
             "status": "unsupported", "verdict": "quote_not_found"},
        ],
    })

    report = ReportComposer().render_markdown(review)
    assert "## Câu hỏi cho tác giả" in report
    assert "How were participants recruited?" in report
    assert "The sample contains 24 participants." in report
    assert "Was funding disclosed?" not in report
    assert "Nhận xét có bằng chứng hỗ trợ: **0**; chưa xác minh: **0**" in report
