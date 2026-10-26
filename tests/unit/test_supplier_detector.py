from clausecheck.rag.supplier_detector import SupplierDetector

SUPPLIERS = [
    {"supplier_id": "S-ACME", "display_name": "Acme Corp", "aliases": ["Acme", "ACME Corporation"]},
    {"supplier_id": "S-BETA", "display_name": "Beta Industries", "aliases": ["Beta"]},
]


def d():
    return SupplierDetector(SUPPLIERS, min_score=85)


def test_exact_and_alias():
    assert d().detect("What are the payment terms with Acme Corp?") == "S-ACME"
    assert d().detect("Does Beta have a liability cap?") == "S-BETA"


def test_misspelling():
    assert d().detect("Payment terms for Acme Corproation?") == "S-ACME"


def test_no_supplier():
    assert d().detect("What is a typical payment term?") is None


def test_follow_up_keeps_previous_and_new_name_overrides():
    assert d().detect("And their notice period?", previous="S-ACME") == "S-ACME"
    assert d().detect("What about Beta Industries?", previous="S-ACME") == "S-BETA"
