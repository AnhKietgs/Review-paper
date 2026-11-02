"""HTTP mapping for background run use cases."""

from fastapi import APIRouter, Depends, Query

from app.api.v1.schemas.runs import RunAccepted, RunRequest
from app.infrastructure.persistence.unit_of_work import UnitOfWork, get_uow
from app.services.run_service import RunService

router = APIRouter(prefix="/api/v1", tags=["runs"])


@router.post("/reviews/{review_id}/runs", status_code=202, response_model=RunAccepted)
def start_run(
    review_id: str, data: RunRequest = RunRequest(), unit: UnitOfWork = Depends(get_uow)
):
    """Queue a new revision for review or verification."""
    return RunService(unit.session).start(review_id, data.mode)


@router.get("/runs/{run_id}")
def get_run(run_id: str, unit: UnitOfWork = Depends(get_uow)):
    """Read persisted progress."""
    return RunService(unit.session).get(run_id)


@router.get("/runs/{run_id}/events")
def get_events(
    run_id: str, after: int = Query(0, ge=0), unit: UnitOfWork = Depends(get_uow)
):
    """Poll ordered trace events after a sequence cursor."""
    return RunService(unit.session).events(run_id, after)


@router.post("/runs/{run_id}/resume", status_code=202, response_model=RunAccepted)
def resume_run(run_id: str, unit: UnitOfWork = Depends(get_uow)):
    """Resume an interrupted or formerly rate limited checkpoint."""
    return RunService(unit.session).resume(run_id)
