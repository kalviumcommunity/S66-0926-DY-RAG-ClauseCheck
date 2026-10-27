from clausecheck.rag.context_builder import build_context
from clausecheck.rag.types import SearchHit


def _hit(i, text="Payment is due Net 45 days.", **meta):
    base = {"doc_id": f"doc-{i}", "page": i, "section": "2. Payment", "clause_no": f"2.{i}",
            "doc_type": "contract", "has_redaction": False}
    base.update(meta)
    return SearchHit(f"c{i}", 1.0, text, base)


def test_markers_numbered_in_order_with_source_lines():
    ctx = build_context([_hit(1), _hit(2), _hit(3)], budget_tokens=2000)
    assert [m for m in ctx.marker_map] == ["C1", "C2", "C3"]
    assert ctx.marker_map["C2"].chunk_id == "c2"
    assert ctx.text.index("[C1]") < ctx.text.index("[C2]") < ctx.text.index("[C3]")
    assert "page 1" in ctx.text and "clause 2.1" in ctx.text


def test_amendment_and_redaction_flags():
    ctx = build_context([_hit(1, doc_type="amendment", parent_doc_id="doc-0", effective_date="2020-03-01",
                              has_redaction=True)], budget_tokens=2000)
    assert "AMENDMENT of doc-0" in ctx.text and "2020-03-01" in ctx.text
    assert "redacted" in ctx.text


def test_budget_never_splits_blocks_and_keeps_first():
    big = "word " * 400
    ctx = build_context([_hit(1, text=big), _hit(2, text=big), _hit(3, text="short")], budget_tokens=500)
    assert [h.chunk_id for h in ctx.used] == ["c1", "c3"]
    assert ctx.text.count("word") == 400
