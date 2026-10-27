def _upload(client, name="contract.pdf", content=b"%PDF-1.4 test", supplier="S-ACME"):
    return client.post("/documents", files={"file": (name, content)}, data={"supplier_id": supplier})


def test_upload_accepted_and_job_status(client):
    r = _upload(client)
    assert r.status_code == 202
    job = client.get(f"/documents/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done" and job["doc_id"] == "upload-x"


def test_upload_duplicate(client):
    r = _upload(client, content=b"duplicate")
    assert r.status_code == 409 and r.json()["doc_id"] == "doc-a"


def test_upload_too_large(client):
    assert _upload(client, content=b"x" * (1024 * 1024 + 1)).status_code == 413


def test_upload_bad_type(client):
    assert _upload(client, name="virus.exe").status_code == 415


def test_upload_requires_supplier(client):
    r = client.post("/documents", files={"file": ("a.pdf", b"%PDF")})
    assert r.status_code == 422


def test_unknown_job(client):
    assert client.get("/documents/jobs/nope").status_code == 404


def test_list_documents_hides_path(client):
    body = client.get("/documents").json()
    assert [d["doc_id"] for d in body["items"]] == ["doc-a"]
    assert "path" not in body["items"][0] and body["next_cursor"] is None
