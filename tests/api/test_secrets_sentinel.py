"""AC-N2.7: the sentinel key never appears in any body, header or log line."""
import logging

from tests.constants import SENTINEL


def test_sentinel_never_leaks(client, container, caplog):
    caplog.set_level(logging.DEBUG)
    calls = [
        ("post", "/sessions", {}),
        ("post", "/chat", {"json": {"question": "Payment terms with Acme?"}}),
        ("post", "/chat/stream", {"json": {"question": "Payment terms with Acme?"}}),
        ("get", "/suppliers", {}),
        ("get", "/chunks/doc-a:p2:2_1", {}),
        ("get", "/chunks/missing", {}),
        ("get", "/documents", {}),
        ("post", "/documents", {"files": {"file": ("a.pdf", b"%PDF")}, "data": {"supplier_id": "S-ACME"}}),
        ("get", "/documents/jobs/job-1", {}),
        ("post", "/feedback", {"json": {"query_id": "q-1", "rating": "up"}}),
        ("get", "/insights/kpis", {}),
        ("get", "/insights/charts", {}),
        ("get", "/insights/tables", {}),
        ("get", "/health", {}),
    ]
    seen = []
    for method, path, kwargs in calls:
        r = getattr(client, method)(path, **kwargs)
        seen.append(r.text + str(dict(r.headers)))

    container.query_service.fail_with = RuntimeError(f"401 invalid key {SENTINEL}")
    for path in ["/chat", "/chat/stream"]:
        r = client.post(path, json={"question": "boom"})
        seen.append(r.text + str(dict(r.headers)))

    for text in seen:
        assert SENTINEL not in text
    assert SENTINEL not in caplog.text
