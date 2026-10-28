def test_the_register_endpoint_lists_contracts_with_their_documents(client):
    body = client.get("/contracts").json()
    assert [(c["id"], c["name"], c["documents"]) for c in body] == [("S-ACME", "Acme Corp", 1)]
    assert set(body[0]) == {
        "id",
        "name",
        "documents",
        "kinds",
        "latest_effective",
        "last_checked",
    }


def test_recent_checks_and_common_questions_start_empty_and_grow_with_use(client, container):
    assert client.get("/checks/recent").json() == []
    assert client.get("/contracts/S-ACME/common-questions").json() == []
    container.query_log.log(
        {
            "query_id": "q-9",
            "created_at": "2026-11-20T11:00:00Z",
            "question": "Payment terms with Acme?",
            "supplier_id": "S-ACME",
            "outcome": "answered",
            "citations": ["doc-a:p2:2_1"],
        }
    )
    recent = client.get("/checks/recent", params={"limit": 3}).json()
    assert recent[0]["contract"] == "Acme Corp" and recent[0]["outcome"] == "1 citation checked"
    assert client.get("/contracts/S-ACME/common-questions").json() == ["Payment terms with Acme?"]


def test_recent_checks_rejects_a_silly_limit(client):
    assert client.get("/checks/recent", params={"limit": 0}).status_code == 422
    assert client.get("/checks/recent", params={"limit": 500}).status_code == 422


def test_the_report_endpoint_takes_a_window_and_a_contract(client):
    report = client.get("/insights/report").json()
    assert report["window"] == {"days": 7, "label": "Last 7 days"}
    assert {"headline", "scorecard", "topics", "unanswered", "failures", "notes", "index"} <= set(
        report
    )
    assert client.get("/insights/report", params={"days": "all"}).json()["window"]["days"] is None
    assert client.get("/insights/report", params={"days": "30"}).json()["window"]["days"] == 30
    # anything that is not a number or "all" falls back to a week instead of failing
    assert client.get("/insights/report", params={"days": "soon"}).json()["window"]["days"] == 7
    one = client.get("/insights/report", params={"contract_id": "S-ACME"}).json()
    assert one["contract"] == "Acme Corp"


def test_the_stream_with_detail_carries_steps_and_checks(client):
    # the fake query service ignores `detail`; this checks the flag is accepted and passed on
    seen = []
    original = client.app.state.container.query_service.stream

    def stream(question, session_id=None, supplier_filter=None, **kw):
        seen.append(kw)
        return original(question, session_id, supplier_filter)

    client.app.state.container.query_service.stream = stream
    client.post("/chat/stream", json={"question": "x", "supplier_id": "S-ACME"})
    client.post(
        "/chat/stream",
        json={"question": "x", "supplier_id": "S-ACME", "detail": True, "strict_scope": True},
    )
    assert seen == [{}, {"strict_scope": True, "detail": True}]


def test_a_badly_written_effective_date_is_refused_before_anything_is_stored(client, container):
    files = {"file": ("a.pdf", b"%PDF-1.4 dates")}
    response = client.post(
        "/documents", files=files, data={"supplier_id": "S-X", "effective_date": "1 April 2024"}
    )
    assert response.status_code == 422 and "YYYY-MM-DD" in response.json()["detail"]


def test_the_effective_date_and_the_amended_document_are_passed_to_the_upload_service(
    client, container
):
    seen = []
    original = container.upload_service.submit

    def submit(filename, content, supplier_id, doc_type="contract", **kw):
        seen.append((doc_type, kw))
        return original(filename, content, supplier_id, doc_type)

    container.upload_service.submit = submit
    client.post(
        "/documents",
        files={"file": ("a.pdf", b"%PDF-1.4 amendment")},
        data={
            "supplier_id": "S-X",
            "doc_type": "amendment",
            "effective_date": "2025-09-01",
            "amends": "doc-a",
        },
    )
    assert seen == [("amendment", {"effective_date": "2025-09-01", "amends": "doc-a"})]
