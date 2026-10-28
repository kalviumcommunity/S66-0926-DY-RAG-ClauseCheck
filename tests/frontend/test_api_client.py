import httpx
import pytest
from components.api_client import ApiClient, ApiUnavailable


def _client(handler):
    return ApiClient(
        "http://api",
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api"),
    )


def test_health_and_suppliers():
    def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "chunks": 5})
        return httpx.Response(
            200, json=[{"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": []}]
        )

    api = _client(handler)
    assert api.health()["status"] == "ok"
    assert api.suppliers()[0]["supplier_id"] == "S-ACME"


def test_upload_outcomes():
    responses = iter(
        [
            httpx.Response(202, json={"job_id": "j1"}),
            httpx.Response(409, json={"detail": "duplicate", "doc_id": "doc-a"}),
            httpx.Response(415, json={"detail": "unsupported file type"}),
        ]
    )
    api = _client(lambda request: next(responses))
    assert api.upload("a.pdf", b"x", "S-ACME", "contract") == {"job_id": "j1"}
    assert api.upload("a.pdf", b"x", "S-ACME", "contract") == {"duplicate": True, "doc_id": "doc-a"}
    with pytest.raises(ValueError):
        api.upload("a.exe", b"x", "S-ACME", "contract")


def test_unavailable():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ApiUnavailable):
        _client(handler).health()
