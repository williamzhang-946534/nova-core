from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from arvuno_core.api.security import require_api_token
from arvuno_core.errors import ArvunoError
from arvuno_core.retention.scheduler import RetentionConflictError, RetentionScheduler

router = APIRouter(
    prefix="/api/retention",
    tags=["Retention"],
    dependencies=[Depends(require_api_token)],
)


class RetentionRunRequest(BaseModel):
    jobs: list[str] = Field(default_factory=list)


def _scheduler(request: Request) -> RetentionScheduler:
    scheduler = getattr(request.app.state, "retention_scheduler", None)
    if not isinstance(scheduler, RetentionScheduler):
        raise ArvunoError(
            code="RETENTION_SCHEDULER_UNAVAILABLE",
            message="The retention scheduler is unavailable.",
            status_code=503,
        )
    return scheduler


@router.get("/policies")
async def retention_policies(request: Request) -> dict[str, object]:
    scheduler = _scheduler(request)
    return {"data": {"policies": scheduler.policies()}}


@router.get("/status")
async def retention_status(request: Request) -> dict[str, object]:
    scheduler = _scheduler(request)
    return {"data": await scheduler.status()}


@router.get("/failures")
async def retention_failures(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, object]:
    scheduler = _scheduler(request)
    return {"data": {"failures": await scheduler.failures(limit=limit)}}


@router.post("/run")
async def run_retention(
    request: Request,
    body: RetentionRunRequest | None = None,
) -> dict[str, object]:
    scheduler = _scheduler(request)
    requested = body.jobs if body is not None else []
    if not requested:
        requested = [policy["name"] for policy in scheduler.policies() if bool(policy["enabled"])]
    if len(set(requested)) != len(requested):
        raise ArvunoError(
            code="RETENTION_JOB_DUPLICATED",
            message="Each retention job may only be requested once.",
            status_code=400,
        )
    try:
        executed = await scheduler.run_manual(requested)
    except RetentionConflictError as exc:
        raise ArvunoError(
            code=exc.code,
            message=exc.message,
            status_code=409,
        ) from exc
    status = await scheduler.status()
    jobs = {
        item["name"]: item
        for item in status["jobs"]
        if isinstance(item, dict) and item.get("name") in executed
    }
    return {"data": {"executed": executed, "jobs": [jobs[name] for name in executed]}}
