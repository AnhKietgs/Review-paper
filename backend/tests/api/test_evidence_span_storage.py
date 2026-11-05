"""Resolved evidence keeps original quotes and text positions through REST storage."""

from uuid import uuid4

from app.harness.evidence import EvidenceResolver, span_source
from app.harness.state import RunScope
from app.infrastructure.persistence.orm_models import FindingRow
from app.infrastructure.persistence.source_catalog import SqlSourceCatalog
from app.infrastructure.persistence.unit_of_work import UnitOfWork


def test_resolved_span_roundtrips_through_review_api(api_client, review_seed):
    review = review_seed(False)
    with UnitOfWork() as unit:
        catalog = SqlSourceCatalog(unit.session)
        chunk = catalog.chunks(review["paper_id"], review["paper_content_version"])[0]
        scope = RunScope(
            main_paper_id=review["paper_id"],
            main_version=review["paper_content_version"],
            rubric_id=review["rubric_id"], rubric_version=review["rubric_version"],
        )
        resolved = EvidenceResolver(catalog).resolve(
            [{"chunk_id": chunk["id"], "span_id": "s0"}], scope, [span_source(chunk)],
        )
        unit.session.add(FindingRow(
            id=str(uuid4()), review_id=review["id"], criterion_code="method",
            kind="analysis", claim="Study describes its sample.",
            compared_paper_ids=[], evidence=resolved, status="pending", verdict="",
        ))
    read = api_client.get(f"/api/v1/reviews/{review['id']}")
    assert read.status_code == 200
    evidence = read.json()["findings"][0]["evidence"][0]
    assert evidence == resolved[0]
    assert evidence["quote"] == chunk["text"][
        evidence["start_char"]:evidence["end_char"]
    ]
