import secrets
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from arvuno_core.config import Settings
from arvuno_core.errors import ArvunoError


def get_app_settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise RuntimeError("The application settings are unavailable.")
    return settings


async def require_api_token(
    settings: Annotated[Settings, Depends(get_app_settings)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(HTTPBearer(auto_error=False)),
    ] = None,
) -> None:
    configured_token = settings.api_token
    if configured_token is None:
        raise ArvunoError(
            code="UNAUTHORIZED",
            message="The API token is not configured.",
            status_code=401,
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ArvunoError(
            code="UNAUTHORIZED", message="A bearer token is required.", status_code=401
        )
    supplied = credentials.credentials
    expected = configured_token.get_secret_value()
    if not expected.strip():
        raise ArvunoError(
            code="UNAUTHORIZED",
            message="The API token is not configured.",
            status_code=401,
        )
    if not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise ArvunoError(code="UNAUTHORIZED", message="The API token is invalid.", status_code=401)
