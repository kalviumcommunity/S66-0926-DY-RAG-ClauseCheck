from clausecheck.rag.citation_validator import normalise_markers, validate
from clausecheck.rag.types import SearchHit

MARKER_MAP = {
    "C1": SearchHit("c1", 1.0, "text", {"doc_id": "d", "page": 1}),
    "C2": SearchHit("c2", 1.0, "text", {"doc_id": "d", "page": 2}),
}


def test_lookalike_markers_are_normalised():
    assert normalise_markers("Net 45【C1】.") == "Net 45[C1]."
    assert normalise_markers("Net 45 ［C2］.") == "Net 45 [C2]."
    assert normalise_markers("Net 45 [ C1 ].") == "Net 45 [C1]."
    assert normalise_markers("Net 45 [C1].") == "Net 45 [C1]."


def test_answer_with_lookalike_markers_keeps_its_citations():
    result = validate(
        "Sicap is not liable for lost profits【C1】. Audit is allowed [C2].", MARKER_MAP
    )
    assert [c.marker for c in result.citations] == ["C1", "C2"]
    assert result.unsupported is False
    assert "【" not in result.answer


def test_an_unknown_marker_is_still_dropped():
    result = validate("Net 45【C9】.", MARKER_MAP)
    assert result.citations == [] and "C9" not in result.answer
