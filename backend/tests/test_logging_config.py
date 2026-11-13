import logging
import logging.handlers
from pathlib import Path

from arvuno_core.logging_config import configure_logging


def test_file_logging_uses_rotation(tmp_path: Path) -> None:
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers
    original_level = root_logger.level
    log_file = tmp_path / "arvuno.log"

    try:
        configure_logging(
            "info",
            log_file,
            max_bytes=4096,
            backup_count=2,
        )
        file_handlers = [
            handler
            for handler in root_logger.handlers
            if isinstance(handler, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].baseFilename == str(log_file.resolve())
        assert file_handlers[0].maxBytes == 4096
        assert file_handlers[0].backupCount == 2
    finally:
        for handler in root_logger.handlers:
            handler.close()
        root_logger.handlers = original_handlers
        root_logger.setLevel(original_level)
