import io
import json
import logging

from clausecheck.core.config import Settings
from clausecheck.core.logging import REDACTED, RedactionFilter, setup_logging
from tests.constants import SENTINEL


def _logger_with_filter(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.filters.clear()
    logger.addFilter(RedactionFilter([SENTINEL, ""]))
    return logger


def test_secret_in_message_is_redacted(caplog):
    logger = _logger_with_filter("test.redact.msg")
    with caplog.at_level(logging.INFO, logger="test.redact.msg"):
        logger.info("calling with key=%s", SENTINEL)
    assert SENTINEL not in caplog.text
    assert REDACTED in caplog.text


def test_secret_in_exception_is_redacted(caplog):
    logger = _logger_with_filter("test.redact.exc")
    with caplog.at_level(logging.INFO, logger="test.redact.exc"):
        try:
            raise RuntimeError(f"401 Unauthorized for key {SENTINEL}")
        except RuntimeError:
            logger.exception("provider failed")
    assert SENTINEL not in caplog.text
    assert "provider failed" in caplog.text


def test_setup_logging_writes_json_and_redacts_all_secret_fields():
    stream = io.StringIO()
    setup_logging(Settings(_env_file=None), stream=stream)
    logging.getLogger("clausecheck.test").warning("keys %s %s", SENTINEL, SENTINEL + "-groq")
    out = stream.getvalue().strip().splitlines()[-1]
    assert SENTINEL not in out
    record = json.loads(out)
    assert {"ts", "level", "logger", "msg"} <= record.keys()
    assert record["level"] == "WARNING"


def test_setup_logging_is_idempotent():
    stream = io.StringIO()
    s = Settings(_env_file=None)
    setup_logging(s, stream=stream)
    setup_logging(s, stream=stream)
    logging.getLogger("clausecheck.once").warning("hello")
    assert stream.getvalue().count("hello") == 1
