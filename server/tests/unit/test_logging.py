import logging

from dokura.logging import RedactingFormatter, redact


def test_redacts_secrets_in_structures_and_text() -> None:
    assert redact({"password": "secret", "name": "dokura"}) == {
        "password": "[已脱敏]",
        "name": "dokura",
    }
    text = redact("Authorization: Bearer api-secret; session=abc; password=hunter2")
    assert "api-secret" not in text
    assert "abc" not in text
    assert "hunter2" not in text


def test_redacts_exception_text_after_formatting() -> None:
    try:
        raise ValueError("api_key=exception-secret")
    except ValueError:
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="request failed",
            args=(),
            exc_info=__import__("sys").exc_info(),
        )
    formatted = RedactingFormatter(logging.Formatter("%(message)s")).format(record)
    assert "exception-secret" not in formatted
    assert "[已脱敏]" in formatted
