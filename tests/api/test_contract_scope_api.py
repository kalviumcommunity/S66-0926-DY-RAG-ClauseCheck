from tests.api.conftest import parse_sse


def _bind(container, session_id="s1", supplier_id="S-ACME"):
    container.sessions.append(session_id, "q", "a", supplier_id)


def test_a_conversation_cannot_be_moved_to_another_contract(client, container):
    _bind(container)
    body = {"question": "Payment terms?", "session_id": "s1", "supplier_id": "S-BETA"}
    for path in ("/chat", "/chat/stream"):
        r = client.post(path, json=body)
        assert r.status_code == 409
        assert "another contract" in r.json()["detail"]


def test_the_same_contract_a_new_conversation_and_no_filter_are_allowed(client, container):
    _bind(container)
    same = {"question": "Payment terms?", "session_id": "s1", "supplier_id": "S-ACME"}
    assert client.post("/chat", json=same).status_code == 200
    fresh = {"question": "Payment terms?", "session_id": "new", "supplier_id": "S-BETA"}
    assert client.post("/chat", json=fresh).status_code == 200
    no_filter = {"question": "Payment terms?", "session_id": "s1"}
    assert client.post("/chat", json=no_filter).status_code == 200
    events = parse_sse(client.post("/chat/stream", json=same).text)
    assert [e for e, _ in events][-1] == "done"


def test_strict_scope_is_passed_on_only_when_asked_for(client, container):
    seen = []

    def answer(question, session_id=None, supplier_filter=None, **kw):
        seen.append(kw)
        return container.query_service.__class__.answer(
            container.query_service, question, session_id, supplier_filter
        )

    container.query_service.answer = answer
    client.post("/chat", json={"question": "x", "supplier_id": "S-ACME"})
    client.post("/chat", json={"question": "x", "supplier_id": "S-ACME", "strict_scope": True})
    assert seen == [{}, {"strict_scope": True}]


def test_display_name_is_passed_to_the_upload_service_only_when_given(client, container):
    seen = []
    original = container.upload_service.submit

    def submit(filename, content, supplier_id, doc_type="contract", **kw):
        seen.append(kw)
        return original(filename, content, supplier_id, doc_type)

    container.upload_service.submit = submit
    files = {"file": ("a.pdf", b"%PDF-1.4 one")}
    client.post("/documents", files=files, data={"supplier_id": "S-X", "display_name": " My Deal "})
    client.post(
        "/documents",
        files={"file": ("b.pdf", b"%PDF-1.4 two")},
        data={"supplier_id": "S-X"},
    )
    assert seen == [{"display_name": "My Deal"}, {}]
