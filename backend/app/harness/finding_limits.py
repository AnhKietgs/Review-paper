"""Count canonical findings across all queues before admitting more review work."""

from collections import Counter


def finding_counts(state) -> Counter:
    """Pending, finished and omission findings share the same criterion allowance."""
    findings = (
        state.pending_findings + state.findings
        + [item["finding"] for item in state.omission_audits]
    )
    return Counter(item["criterion_code"] for item in {
        item["id"]: item for item in findings
    }.values())


def finding_policy(state, criteria) -> dict:
    """Tell producers remaining slots so they avoid generating discarded drafts."""
    counts = finding_counts(state)
    return {
        "max_per_criterion": state.max_findings_per_criterion,
        "remaining": {
            item["code"]: max(
                0, state.max_findings_per_criterion - counts[item["code"]],
            ) for item in criteria
        },
    }
