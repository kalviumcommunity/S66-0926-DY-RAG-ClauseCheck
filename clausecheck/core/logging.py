"""JSON logging with secret redaction."""

import json
import logging
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import IO

from pydantic import SecretStr

from clausecheck.core.config import Settings

REDACTED = "[REDACTED]"

_ADDED_HANDLER_ATTR = "_clausecheck_handler"


class RedactionFilter(logging.Filter):
    """Replace every known secret in a record's message and exception text."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        """Redact the record in place and always let it through."""
        record.msg = self._redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = self._redact(formatted)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = self._redact(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    """Format records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as a JSON string with ts, level, logger and msg."""
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_text:
            payload["exc"] = record.exc_text
        return json.dumps(payload)


def setup_logging(settings: Settings, stream: IO[str] | None = None) -> logging.Handler:
    """Configure the root logger with a redacting JSON handler and return that handler."""
    secrets = [
        value.get_secret_value()
        for name in type(settings).model_fields
        if isinstance(value := getattr(settings, name), SecretStr)
    ]
    root = logging.getLogger()
    for old in [h for h in root.handlers if getattr(h, _ADDED_HANDLER_ATTR, False)]:
        root.removeHandler(old)

    handler = logging.StreamHandler(stream or sys.stderr)
    setattr(handler, _ADDED_HANDLER_ATTR, True)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter(secrets))
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    return handler
