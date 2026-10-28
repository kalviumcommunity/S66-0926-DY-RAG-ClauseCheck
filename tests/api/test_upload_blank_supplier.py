def test_blank_supplier_id_is_rejected(client):
    for blank in ("", "   "):
        r = client.post(
            "/documents", files={"file": ("a.pdf", b"%PDF")}, data={"supplier_id": blank}
        )
        assert r.status_code == 422 and "supplier_id" in r.json()["detail"]
