import logging

from nova_core.logging_config import redact_sensitive_text, redact_sensitive_value


def test_sensitive_key_value_pairs_are_redacted_in_text() -> None:
    text = "api_key=abc123 token:def456 password=ghi789 bearer jkl012"

    result = redact_sensitive_text(text)

    assert "abc123" not in result
    assert "def456" not in result
    assert "ghi789" not in result
    assert "jkl012" not in result
    assert result.count("[REDACTED]") == 4


def test_structured_sensitive_fields_are_redacted_recursively() -> None:
    value = {
        "api_key": "abc123",
        "nested": {"HOME_ASSISTANT_TOKEN": "def456", "safe": "visible"},
        "authorization": ["credential"],
    }

    result = redact_sensitive_value(value)

    assert result["api_key"] == "[REDACTED]"
    assert result["nested"]["HOME_ASSISTANT_TOKEN"] == "[REDACTED]"
    assert result["nested"]["safe"] == "visible"
    assert result["authorization"] == "[REDACTED]"


def test_log_formatter_redacts_messages_and_exceptions() -> None:
    record = logging.LogRecord(
        name="nova",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token=%s",
        args=("secret-value",),
        exc_info=None,
    )

    message = redact_sensitive_text(record.getMessage())

    assert message == "token=[REDACTED]"
