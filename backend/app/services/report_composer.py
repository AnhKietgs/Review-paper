"""Deterministic Markdown composition from AI-checked findings."""

from app.api.v1.schemas.reviews import ReviewRead

SECTIONS = [
    ("Mục tiêu", {"objective", "goal"}),
    ("Phương pháp", {"method", "methodology", "general"}),
    ("Kết quả", {"results", "result"}),
    ("Đóng góp", {"contributions", "contribution", "novelty"}),
    ("Điểm mạnh", {"strength", "strengths"}),
    ("Hạn chế", {"limitation", "limitations", "limits"}),
    ("So sánh với công trình được chọn", {"comparison"}),
    ("Câu hỏi cho tác giả", {"question", "questions"}),
]


class ReportComposer:
    """Generate a report without an extra LLM call at export time."""

    @staticmethod
    def _finding_lines(finding) -> list[str]:
        lines = [f"### {finding.claim}", "", f"Trạng thái: `{finding.status}`.", ""]
        if finding.status != "supported":
            lines += [
                "⚠️ AI chưa xác minh được nhận xét này. "
                "Không dùng như kết luận khoa học.",
                "",
            ]
        lines += [finding.verdict, ""]
        for item in finding.evidence:
            place = "PDF trang" if item["locator_type"] == "pdf_page" else "DOCX đoạn"
            if finding.status != "supported":
                lines += ["Đoạn trích dưới đây chưa đủ để chứng minh nhận xét:", ""]
            lines += [
                f"> {item['quote']}",
                "",
                f"Nguồn: `{item['paper_id']}` · v{item['content_version']} · "
                f"{place} {item['locator_value']} · chunk `{item['chunk_id']}`.",
                "",
            ]
        return lines

    def render_markdown(self, review: ReviewRead) -> str:
        """Render stable sections and evidence in deterministic order."""
        lines = [
            "# Paper Review",
            "",
            f"Review: `{review.id}` · revision {review.revision}",
            "",
            f"Paper: `{review.paper_id}` · nội dung v{review.paper_content_version}",
            "",
            f"Rubric: `{review.rubric_id}` · v{review.rubric_version}",
            "",
            f"Trạng thái báo cáo: **{review.status}**",
            "",
            f"Nhận xét có bằng chứng hỗ trợ: "
            f"**{sum(item.status == 'supported' for item in review.findings)}**; "
            f"chưa xác minh: "
            f"**{sum(item.status != 'supported' for item in review.findings)}**.",
            "",
        ]
        if review.reviewer_edits.get("summary"):
            lines += [
                "## Ghi chú của người dùng",
                "",
                review.reviewer_edits["summary"],
                "",
            ]
        remaining = sorted(
            (finding for finding in review.findings if finding.status == "supported"),
            key=lambda finding: (finding.criterion_code, finding.id),
        )
        for title, keys in SECTIONS:
            lines += [f"## {title}", ""]
            selected = [
                finding
                for finding in remaining
                if finding.kind in keys or finding.criterion_code in keys
            ]
            remaining = [finding for finding in remaining if finding not in selected]
            if not selected:
                lines += ["Chưa có nhận xét đã kiểm chứng cho mục này.", ""]
            for finding in selected:
                lines += self._finding_lines(finding)
        if remaining:
            lines += ["## Nhận xét bổ sung", ""]
            for finding in remaining:
                lines += self._finding_lines(finding)
        unverified = sorted(
            (finding for finding in review.findings if finding.status != "supported"),
            key=lambda finding: (finding.criterion_code, finding.id),
        )
        if unverified:
            lines += [
                "## Nhận xét chưa xác minh",
                "",
                "Các nhận xét này đã được AI kiểm tra nhưng chưa đủ bằng chứng "
                "để dùng như kết luận. Hệ thống giữ lại để thể hiện giới hạn đánh giá.",
                "",
            ]
            for finding in unverified:
                lines += self._finding_lines(finding)
        references = review.analysis.get("references", {})
        if not review.references:
            lines += [
                "So sánh: `not_assessed` — người dùng không chọn paper đối chiếu.",
                "",
            ]
        for paper_id, assessment in sorted(references.items()):
            lines += [
                f"- `{paper_id}`: {assessment['status']} — {assessment['reason']}"
            ]
        coverage = review.analysis.get("coverage", {})
        lines += [
            "",
            "## Giới hạn đánh giá",
            "",
            f"Đã xử lý {coverage.get('processed', 0)} chunk của paper chính; "
            f"còn {coverage.get('remaining', 0)} chunk.",
            "",
            "So sánh chỉ áp dụng cho các trích đoạn của nguồn do người dùng chọn. "
            "Dẫn chứng đúng vị trí không tự chứng minh tính đúng đắn khoa học "
            "hoặc tính mới "
            "so với toàn bộ lĩnh vực. Báo cáo ghi riêng mọi nhận xét "
            "chưa được xác minh.",
            "",
        ]
        return "\n".join(lines)
