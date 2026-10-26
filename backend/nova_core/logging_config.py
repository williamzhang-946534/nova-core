import json
import logging
import re
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_SENSITIVE_KEY = re.compile(r"(?i)(api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s,;}]+)")
_BEARER_TOKEN = re.compile(r"(?i)(bearer\s+)([^\s,;}]+)")
_SENSITIVE_KEY_NAME = re.compile(
    r"(?i).*(api[_-]?key|token|secret|password|authorization|credential).*"
)


def redact_sensitive_text(value: str) -> str:
    value = _SENSITIVE_KEY.sub(r"\1\2[REDACTED]", value)
    return _BEARER_TOKEN.sub(r"\1[REDACTED]", value)


def redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {
            redact_sensitive_value(key): "[REDACTED]"
            if _SENSITIVE_KEY_NAME.fullmatch(str(key))
            else redact_sensitive_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    return value


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = correlation_id_var.get()  # type: ignore[attr-defined]
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_sensitive_text(record.getMessage()),
            "correlation_id": getattr(record, "correlation_id", None),
        }
        structured_payload = getattr(record, "payload", None)
        if structured_payload is not None:
            payload["payload"] = redact_sensitive_value(structured_payload)
        if record.exc_info:
            payload["exception"] = redact_sensitive_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, log_file: Path | None = None) -> None:
    formatter = JsonFormatter()
    correlation_filter = CorrelationIdFilter()
    handlers: list[logging.Handler] = []

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(correlation_filter)
    handlers.append(console_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(correlation_filter)
        handlers.append(file_handler)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    for handler in handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(level.upper())
