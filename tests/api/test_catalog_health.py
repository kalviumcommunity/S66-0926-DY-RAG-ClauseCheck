def test_suppliers(client):
    assert client.get("/suppliers").json() == [
        {"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": ["Acme"]}
    ]


def test_chunk_found_and_missing(client):
    r = client.get("/chunks/doc-a:p2:2_1")
    assert r.status_code == 200 and r.json()["text"] and r.json()["page"] == 2
    assert client.get("/chunks/missing").status_code == 404


def test_health_ok(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert (body["documents"], body["chunks"], body["suppliers"]) == (1, 1, 1)
    assert body["checks"] == {"sqlite": True, "vector_store": True, "llm_configured": True}


def test_health_degraded_without_chunks(client, container):
    container.conn.execute("DELETE FROM chunks")
    container.conn.commit()
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "degraded"
