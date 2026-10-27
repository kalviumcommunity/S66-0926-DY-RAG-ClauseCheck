from clausecheck.rag.supplier_detector import SupplierDetector

SUPPLIERS = [
    {
        "supplier_id": "helixa",
        "display_name": "Helixa Cloud Systems",
        "aliases": ["helixa-cloud-systems"],
    },
    {"supplier_id": "orion", "display_name": "Orion", "aliases": []},
]


def d():
    return SupplierDetector(SUPPLIERS, min_score=85)


def test_supplier_name_becomes_the_supplier():
    out = d().strip_names("Which law governs the Helixa Cloud Systems agreement?", "helixa")
    assert out == "Which law governs the Supplier agreement?"


def test_possessive_is_kept_as_a_possessive():
    out = d().strip_names("What is Orion's liability for goods lost in transit?", "orion")
    assert out == "What is the Supplier's liability for goods lost in transit?"


def test_the_sentence_stays_whole():
    # deleting the name left "What insurance must carry?", which the re-ranker scored badly
    out = d().strip_names("What insurance must Orion carry?", "orion")
    assert out == "What insurance must the Supplier carry?"


def test_full_company_name_goes_when_the_stored_name_is_shorter():
    # the supplier was uploaded as "Orion" but the question says "Orion Freight Lines Pvt. Ltd."
    d_ = d()
    assert (
        d_.strip_names("What are the payment terms with Orion Freight Lines Pvt. Ltd.?", "orion")
        == "What are the payment terms with the Supplier?"
    )
    assert (
        d_.strip_names("What is Orion Freight Lines' monthly fee for Surat Plant 1?", "orion")
        == "What is the Supplier's monthly fee for Surat Plant 1?"
    )
    assert (
        d_.strip_names("How fast must Orion Freight Lines attend a lift breakdown?", "orion")
        == "How fast must the Supplier attend a lift breakdown?"
    )


def test_other_suppliers_and_no_supplier_are_left_alone():
    q = "Which law governs the Helixa Cloud Systems agreement?"
    assert d().strip_names(q, "orion") == q
    assert d().strip_names(q, None) == q
