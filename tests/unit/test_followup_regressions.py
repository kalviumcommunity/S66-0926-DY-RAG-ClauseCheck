from clausecheck.rag.citation_validator import validate
from clausecheck.rag.supplier_detector import SupplierDetector
from clausecheck.rag.types import SearchHit

SUPPLIERS = [
    {"supplier_id": "mmi", "display_name": "MMI", "aliases": []},
    {"supplier_id": "netgear", "display_name": "NETGEAR", "aliases": []},
]


def test_short_name_does_not_match_inside_a_word():
    d = SupplierDetector(SUPPLIERS, min_score=85)
    assert d.detect("Is there a minimum annual purchase commitment?") is None
    assert d.detect("What does the MMI agreement say about notice?") == "mmi"
    assert d.detect("Terms with MMI.") == "mmi"


def test_abbreviation_full_stop_is_not_a_sentence_end():
    marker_map = {"C1": SearchHit("c1", 1.0, "text", {"doc_id": "d"})}
    answer = (
        'The parties are Kestrel Manufacturing Ltd. (the "Buyer") and '
        'Verdant Polymers Pvt. Ltd. (the "Supplier") [C1].'
    )
    assert validate(answer, marker_map).unsupported is False


def test_uncited_sentence_is_still_flagged():
    marker_map = {"C1": SearchHit("c1", 1.0, "text", {"doc_id": "d"})}
    assert validate("Payment is Net 45 [C1]. Delivery is in 5 days.", marker_map).unsupported
