from clausecheck.rag.supplier_detector import SupplierDetector
from clausecheck.services.sessions import SessionStore

SUPPLIERS = [
    {"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": ["Acme"]},
    {"supplier_id": "S-BETA", "display_name": "Beta Industries", "aliases": ["Beta"]},
    {"supplier_id": "mmi", "display_name": "MMI", "aliases": []},
]


def d():
    return SupplierDetector(SUPPLIERS, min_score=85)


def test_other_supplier_finds_a_different_contract_in_the_question():
    assert d().other_supplier("Payment terms with Acme Corp?", "S-BETA") == "S-ACME"
    assert d().other_supplier("Does Beta have a cap, and what about Acme?", "S-BETA") == "S-ACME"


def test_other_supplier_ignores_the_scoped_contract_and_unnamed_questions():
    assert d().other_supplier("Payment terms with Beta Industries?", "S-BETA") is None
    assert d().other_supplier("And their notice period?", "S-BETA") is None
    # a short name inside another word is not a mention ("MMI" in "commitment")
    assert d().other_supplier("Is there a minimum purchase commitment?", "S-BETA") is None


def test_display_name_falls_back_to_the_id():
    assert d().display_name("S-ACME") == "Acme Corp"
    assert d().display_name("unknown-id") == "unknown-id"


def test_scope_of_a_conversation_is_its_first_answers_supplier():
    store = SessionStore(3)
    assert store.scope_of(None) is None and store.scope_of("nope") is None
    sid = store.new()
    assert store.scope_of(sid) is None
    store.append(sid, "q", "a", "S-ACME")
    assert store.scope_of(sid) == "S-ACME"
    assert "nope" not in store._sessions  # looking up a scope does not create a session
