from fastapi import APIRouter, Request

from arvuno_core import __version__
from arvuno_core.config import Settings
from arvuno_core.schemas.health import HealthResponse

router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Report process health without checking database or external services."""

    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        version=__version__,
        environment=settings.environment,
    )
