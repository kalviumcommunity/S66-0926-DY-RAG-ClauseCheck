from clausecheck.llm.client import describe_error
from tests.constants import SENTINEL


class RateLimitError(Exception):
    status_code = 429


class ClientError(Exception):
    code = 404


def test_includes_the_status_code_but_never_the_message():
    out = describe_error(RateLimitError(f"too many requests for key {SENTINEL}"))
    assert out == "RateLimitError 429" and SENTINEL not in out
    assert describe_error(ClientError(f"no such model {SENTINEL}")) == "ClientError 404"


def test_without_a_status_code_it_is_just_the_type():
    assert describe_error(TimeoutError(SENTINEL)) == "TimeoutError"
