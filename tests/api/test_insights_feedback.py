def test_feedback(client):
    client.post("/chat", json={"question": "Payment terms with Acme?"})
    assert client.post("/feedback", json={"query_id": "q-1", "rating": "up"}).status_code == 204
    assert client.post("/feedback", json={"query_id": "nope", "rating": "up"}).status_code == 404
    assert client.post("/feedback", json={"query_id": "q-1", "rating": "meh"}).status_code == 422


def test_kpis(client):
    client.post("/chat", json={"question": "Payment terms with Acme?"})
    k = client.get("/insights/kpis").json()
    assert set(k) == {"questions_asked", "answer_rate", "median_time_to_checked_answer_ms",
                      "median_ttft_ms", "citation_accuracy"}
    assert k["questions_asked"] == 1 and k["answer_rate"] == 1.0


def test_charts_and_tables_shape(client):
    assert set(client.get("/insights/charts").json()) == {
        "outcomes_by_day", "latency_by_day", "questions_by_topic", "documents_by_source"}
    assert set(client.get("/insights/tables").json()) == {
        "supplier_activity", "unanswered", "evaluation", "coverage"}
