import logging
import re
from typing import Any


_SECRET_KEY = re.compile(r"(?i)(authorization|api[-_]?key|password|session|cookie)")
_SECRET_FIELDS = re.compile(
    r"(?i)(authorization|api[-_]?key|password|session|cookie)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[已脱敏]" if _SECRET_KEY.fullmatch(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact(item) for item in value)
    if isinstance(value, str):
        value = _BEARER.sub(r"\1[已脱敏]", value)
        return _SECRET_FIELDS.sub(r"\1\2[已脱敏]", value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.msg)
        if record.args:
            record.args = redact(record.args)
        return True


class RedactingFormatter(logging.Formatter):
    def __init__(self, delegate: logging.Formatter | None = None) -> None:
        super().__init__()
        self.delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        formatted = (
            self.delegate.format(record) if self.delegate else super().format(record)
        )
        return redact(formatted)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(
        RedactingFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    for existing in logging.Logger.manager.loggerDict.values():
        if not isinstance(existing, logging.Logger):
            continue
        for existing_handler in existing.handlers:
            existing_handler.addFilter(RedactingFilter())
            if not isinstance(existing_handler.formatter, RedactingFormatter):
                existing_handler.setFormatter(
                    RedactingFormatter(existing_handler.formatter)
                )
