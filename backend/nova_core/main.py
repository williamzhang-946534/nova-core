import uvicorn

from nova_core.app import create_app
from nova_core.config import get_settings
from nova_core.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level, settings.resolved_log_file)
app = create_app(settings)


def run() -> None:
    uvicorn.run(
        "nova_core.main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
    )


if __name__ == "__main__":
    run()
