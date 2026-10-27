from clausecheck.llm.client import describe_error

SECRET = "TEST-SENTINEL-7f3a"


class RateLimitError(Exception):
    status_code = 429


class ClientError(Exception):
    code = 404


def test_includes_the_status_code_but_never_the_message():
    out = describe_error(RateLimitError(f"too many requests for key {SECRET}"))
    assert out == "RateLimitError 429" and SECRET not in out
    assert describe_error(ClientError(f"no such model {SECRET}")) == "ClientError 404"


def test_without_a_status_code_it_is_just_the_type():
    assert describe_error(TimeoutError(SECRET)) == "TimeoutError"
