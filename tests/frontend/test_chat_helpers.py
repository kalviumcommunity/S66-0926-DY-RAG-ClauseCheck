from components.chat import REFUSAL_COPY, StreamCollector


def _events(outcome="answered", reason=None):
    return [
        ("meta", {"query_id": "q-1", "supplier_id": "S-ACME"}),
        ("sources", {"sources": [{"marker": "C1", "chunk_id": "c1"}]}),
        ("token", {"text": "Net "}),
        ("token", {"text": "45 [C1]."}),
        ("citations", {"citations": [{"marker": "C1", "chunk_id": "c1"}], "unsupported": False}),
        ("done", {"outcome": outcome, "refusal_reason": reason, "timings": {}}),
    ]


def test_collector_yields_only_tokens_and_builds_message():
    c = StreamCollector(_events())
    assert "".join(c) == "Net 45 [C1]."
    m = c.message
    assert m["role"] == "assistant" and m["content"] == "Net 45 [C1]." and m["query_id"] == "q-1"
    assert m["citations"][0]["chunk_id"] == "c1" and m["outcome"] == "answered"


def test_no_citation_refusal_replaces_content():
    c = StreamCollector(_events("refused", "no_citations"))
    list(c)
    assert c.message["content"] == REFUSAL_COPY and c.message["outcome"] == "refused"


def test_error_event_recorded():
    c = StreamCollector([("error", {"message": "Backend down"}), ("done", {"outcome": "error"})])
    assert list(c) == []
    assert c.message["outcome"] == "error" and c.message["error"] == "Backend down"


def test_refusal_copy_matches_backend():
    from clausecheck.rag.generator import REFUSAL_TEXT

    assert REFUSAL_COPY == REFUSAL_TEXT
