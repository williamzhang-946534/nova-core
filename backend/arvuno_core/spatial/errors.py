from arvuno_core.errors import ArvunoError


class SpatialError(ArvunoError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "SPATIAL_INVALID",
        status_code: int = 400,
    ) -> None:
        super().__init__(code=code, message=message, status_code=status_code)


class SpaceNotFoundError(SpatialError):
    def __init__(self) -> None:
        super().__init__(
            "The space does not exist.",
            code="SPACE_NOT_FOUND",
            status_code=404,
        )


__all__ = ["SpaceNotFoundError", "SpatialError"]
