"""Source-selected evidence preserves exact Unicode text and frozen identities."""

from copy import deepcopy

import pytest

from app.harness.evidence import EvidenceResolutionError, EvidenceResolver, build_spans
from app.harness.state import RunScope


class Catalog:
    def __init__(self):
        self.source = {
            "id": "chunk", "paper_id": "main", "content_version": 1,
            "text": "Mục tiêu nghiên cứu.\r\nĐạo đức: giữ nguyên tiếng Việt và 😀.",
            "locator": {"type": "pdf_page", "value": "5", "status": "resolved"},
        }

    def chunk(self, chunk_id):
        return self.source if chunk_id == "chunk" else None

    def is_active(self, _paper_id):
        return True


def setup_evidence():
    catalog = Catalog()
    sources = [{**catalog.source, "spans": build_spans(catalog.source["text"])}]
    scope = RunScope(
        main_paper_id="main", main_version=1, rubric_id="rubric", rubric_version=1,
    )
    return catalog, sources, scope


def test_spans_cover_source_exactly_and_offsets_are_unicode_codepoints():
    text = ("Tiếng Việt 😀.\r\nKhông thay đổi dấu hay khoảng trắng. " * 20) + "x" * 700
    spans = build_spans(text)
    assert spans == build_spans(text)
    assert "".join(span["text"] for span in spans) == text
    assert len({span["id"] for span in spans}) == len(spans)
    assert all(len(span["text"]) <= 480 for span in spans)
    assert all(text[s["start_char"]:s["end_char"]] == s["text"] for s in spans)
    assert build_spans("") == []


def test_resolver_derives_quote_identity_page_and_offsets_from_catalog():
    catalog, sources, scope = setup_evidence()
    result = EvidenceResolver(catalog).resolve(
        [{"chunk_id": "chunk", "span_id": "s0"}], scope, sources,
    )
    assert result == [{
        "paper_id": "main", "content_version": 1, "chunk_id": "chunk",
        "quote": catalog.source["text"], "locator_type": "pdf_page",
        "locator_value": "5", "span_id": "s0", "start_char": 0,
        "end_char": len(catalog.source["text"]),
    }]


@pytest.mark.parametrize("selection,reason", [
    ({"chunk_id": "unseen", "span_id": "s0"}, "source_not_supplied"),
    ({"chunk_id": "chunk", "span_id": "s99"}, "span_not_supplied"),
])
def test_resolver_rejects_sources_or_spans_not_shown_to_this_agent(selection, reason):
    catalog, sources, scope = setup_evidence()
    with pytest.raises(EvidenceResolutionError, match=reason):
        EvidenceResolver(catalog).resolve([selection], scope, sources)


@pytest.mark.parametrize("change,reason", [
    ({"content_version": 2}, "source_version_mismatch"),
    ({"paper_id": "unselected-reference"}, "source_version_mismatch"),
    ({"locator": None}, "unresolved_locator"),
    ({"text": "Changed source content."}, "source_content_changed"),
])
def test_resolver_rejects_changed_or_unresolved_sources(change, reason):
    catalog, sources, scope = setup_evidence()
    catalog.source.update(change)
    with pytest.raises(EvidenceResolutionError, match=reason):
        EvidenceResolver(catalog).resolve(
            [{"chunk_id": "chunk", "span_id": "s0"}], scope, sources,
        )


def test_model_cannot_supply_its_own_quote_or_page():
    catalog, sources, scope = setup_evidence()
    selection = {"chunk_id": "chunk", "span_id": "s0", "quote": "Invented"}
    with pytest.raises(EvidenceResolutionError, match="invalid_selection"):
        EvidenceResolver(catalog).resolve([selection], scope, sources)


def test_docx_paragraph_locator_is_derived_without_model_page_selection():
    catalog, sources, scope = setup_evidence()
    catalog.source["locator"] = {
        "type": "docx_paragraph", "value": "12", "status": "resolved",
    }
    evidence = EvidenceResolver(catalog).resolve(
        [{"chunk_id": "chunk", "span_id": "s0"}], scope, sources,
    )
    assert evidence[0]["locator_type"] == "docx_paragraph"
    assert evidence[0]["locator_value"] == "12"


def test_selected_reference_positions_are_independently_rechecked_by_gate():
    from app.harness.output_gate import OutputGate

    catalog, sources, scope = setup_evidence()
    evidence = EvidenceResolver(catalog).resolve(
        [{"chunk_id": "chunk", "span_id": "s0"}], scope, sources,
    )
    finding = {
        "criterion_code": "method", "claim": "Một nhận xét cần kiểm chứng.",
        "kind": "analysis", "evidence": evidence,
    }
    assert OutputGate(catalog).validate(finding, scope).passed
    changed = deepcopy(finding)
    changed["evidence"][0]["start_char"] = 1
    assert not OutputGate(catalog).validate(changed, scope).passed
    changed = deepcopy(finding)
    changed["evidence"][0]["quote"] = "Mục tiêu nghiên cứu."
    assert not OutputGate(catalog).validate(changed, scope).passed
