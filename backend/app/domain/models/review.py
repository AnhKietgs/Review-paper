"""Review revision states."""

from enum import StrEnum


class ReviewStatus(StrEnum):
    """Review lifecycle with an autonomous completed report."""

    DRAFT = "draft"
    COMPLETED = "completed"
    APPROVED = "approved"
