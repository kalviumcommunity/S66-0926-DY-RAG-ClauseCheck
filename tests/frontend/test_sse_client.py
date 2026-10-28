import httpx
from components.sse_client import BACKEND_DOWN, parse_sse, stream_chat


def test_parse_sse_events():
    lines = [
        "event: meta",
        'data: {"query_id": "q"}',
        "",
        ": keep-alive",
        "",
        "event: token",
        'data: {"text": "Net "}',
        "",
        "event: token",
        'data: {"text": "45"}',
        "",
    ]
    assert list(parse_sse(lines)) == [
        ("meta", {"query_id": "q"}),
        ("token", {"text": "Net "}),
        ("token", {"text": "45"}),
    ]


def test_stream_chat_parses_live_response():
    body = 'event: token\ndata: {"text": "Hi"}\n\nevent: done\ndata: {"outcome": "answered"}\n\n'

    def handler(request):
        assert request.url.path == "/chat/stream"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api")
    events = list(stream_chat("http://api", {"question": "q"}, client=client))
    assert events == [("token", {"text": "Hi"}), ("done", {"outcome": "answered"})]


def test_stream_chat_backend_down():
    def handler(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://api")
    events = list(stream_chat("http://api", {"question": "q"}, client=client))
    assert events == [("error", {"message": BACKEND_DOWN}), ("done", {"outcome": "error"})]
