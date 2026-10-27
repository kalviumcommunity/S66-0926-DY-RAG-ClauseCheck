from clausecheck.services.sessions import SessionStore


def test_new_and_get_or_create():
    store = SessionStore(history_turns=2)
    sid = store.new()
    assert store.get_or_create(sid).session_id == sid
    assert store.get_or_create(None).session_id != sid
    assert store.get_or_create("custom").session_id == "custom"


def test_history_trimmed_and_supplier_kept():
    store = SessionStore(history_turns=2)
    sid = store.new()
    store.append(sid, "q1", "a1", "S-ACME")
    store.append(sid, "q2", "a2", None)
    store.append(sid, "q3", "a3", None)
    s = store.get_or_create(sid)
    assert [t.question for t in s.turns] == ["q2", "q3"]
    assert s.supplier_id == "S-ACME"
