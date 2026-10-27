from tests.api.conftest import parse_sse


def test_sessions(client):
    r = client.post("/sessions")
    assert r.status_code == 201 and len(r.json()["session_id"]) == 32


def test_chat_answered(client):
    r = client.post("/chat", json={"question": "Payment terms with Acme?"})
    assert r.status_code == 200
    body = r.json()
    assert body["outcome"] == "answered" and body["citations"][0]["chunk_id"] == "doc-a:p2:2_1"
    assert {
        "query_id",
        "answer",
        "refusal_reason",
        "supplier_id",
        "cached",
        "unsupported",
        "timings",
    } <= body.keys()
    assert r.headers["x-request-id"]


def test_chat_refused(client):
    body = client.post("/chat", json={"question": "please refuse"}).json()
    assert body["outcome"] == "refused" and body["citations"] == []


def test_chat_validation(client):
    assert client.post("/chat", json={"question": ""}).status_code == 422
    assert client.post("/chat", json={"question": "x" * 1001}).status_code == 422


def test_stream_event_order(client):
    r = client.post("/chat/stream", json={"question": "Payment terms with Acme?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    types = [e for e, _ in parse_sse(r.text)]
    assert types == ["meta", "sources", "token", "token", "citations", "done"]


def test_stream_error_event(client, container):
    container.query_service.fail_with = RuntimeError("provider exploded")
    events = parse_sse(client.post("/chat/stream", json={"question": "x"}).text)
    assert [e for e, _ in events][-2:] == ["error", "done"]
    assert "exploded" not in events[-2][1]["message"]
    assert events[-1][1]["outcome"] == "error"


def test_chat_internal_error_is_generic(client, container):
    container.query_service.fail_with = RuntimeError("provider exploded")
    r = client.post("/chat", json={"question": "x"})
    assert (
        r.status_code == 500 and r.json()["detail"] == "internal error" and "request_id" in r.json()
    )
