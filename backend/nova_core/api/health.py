from typing import Annotated

from fastapi import APIRouter, Depends

from nova_core import __version__
from nova_core.config import Settings, get_settings
from nova_core.schemas.health import HealthResponse

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
