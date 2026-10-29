from typing import Annotated

from fastapi import APIRouter, Depends

from arvuno_core import __version__
from arvuno_core.config import Settings, get_settings
from arvuno_core.schemas.health import HealthResponse

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse)
async def get_health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Report process health without checking database or external services."""

    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment,
    )
