from clausecheck.rag.checks import (
    check_answer,
    clause_pages,
    highlight_spans,
    key_figures,
    normalise,
    term_name,
    terms_found,
)
from clausecheck.rag.types import SearchHit


def hit(chunk_id, text, **meta):
    return SearchHit(chunk_id, 1.0, text, dict(meta))


ORIGINAL = hit(
    "o:5_1",
    "5.1 Payment Period. The Supplier shall invoice monthly. Payment shall be made within "
    "thirty (30) days of receipt of a valid invoice (Net 30).",
    doc_id="orig",
    clause_no="5.1",
    page=2,
    doc_type="contract",
    effective_date="2023-02-01",
)
AMENDMENT = hit(
    "a:5_1",
    'Section 5.1 (Payment Period) of the Agreement is deleted and replaced with: "5.1 Payment '
    'Period. Payment shall be made within forty-five (45) days of receipt (Net 45)."',
    doc_id="amd",
    clause_no="5.1",
    page=1,
    doc_type="amendment",
    effective_date="2024-04-01",
    parent_doc_id="orig",
)
MARKERS = {"C1": AMENDMENT, "C2": ORIGINAL}
INFO = {"orig": {"title": "SERVICE.pdf"}, "amd": {"title": "AMD1.pdf"}}.get


def test_normalise_treats_the_same_figure_written_differently_as_equal():
    assert normalise("$40,000") == normalise("40000") == normalise("40,000.00") == "40000"
    assert normalise("99.95%") == "99.95" and normalise("04") == "4"


def test_a_clean_answer_is_checked():
    result = check_answer("Payment is due within 45 days [C1].", {"C1": AMENDMENT}, INFO)
    assert result.status == "checked"
    assert result.to_dict()["citations"] == {"found": 1, "total": 1}
    assert result.to_dict()["numbers"] == {"matched": 1, "total": 1, "unverified": []}


def test_an_invented_figure_and_an_uncited_sentence_are_flagged():
    answer = "Payment is due within 45 days [C1]. Interest is 1.5% per month."
    result = check_answer(answer, {"C1": AMENDMENT}, INFO)
    assert result.status == "verify" and result.uncited_sentences == 1
    assert result.unverified == [{"value": "1.5%", "marker": None}]


def test_a_figure_in_no_cited_clause_is_flagged_even_with_a_citation():
    result = check_answer("The late fee is 3% [C1].", {"C1": AMENDMENT}, INFO)
    assert result.unverified == [{"value": "3%", "marker": "C1"}] and result.status == "verify"


def test_replacing_net_30_is_fine_when_the_original_is_cited_elsewhere():
    answer = "The period is Net 45, replacing Net 30 [C1]. It was 30 days before [C2]."
    result = check_answer(answer, MARKERS, INFO)
    assert result.unverified == [] and result.status == "checked"


def test_a_dropped_marker_means_not_every_citation_was_found():
    result = check_answer("Payment is due in 45 days [C1].", {"C1": AMENDMENT}, INFO, dropped=1)
    assert result.to_dict()["citations"] == {"found": 1, "total": 2}
    assert result.status == "verify"


def test_a_cited_amendment_is_reported_with_the_clause_it_replaces():
    result = check_answer("Net 45 applies [C1].", {"C1": AMENDMENT}, INFO)
    assert result.amendments == [
        {
            "marker": "C1",
            "title": "AMD1.pdf",
            "effective_date": "2024-04-01",
            "clause_no": "5.1",
            "replaces_clause": "5.1",
        }
    ]


def test_a_date_from_the_clause_metadata_counts_as_in_the_clause():
    result = check_answer("The amendment is effective 2024-04-01 [C1].", {"C1": AMENDMENT}, INFO)
    assert result.unverified == []


def test_terms_found_shows_value_source_and_whether_it_is_in_force():
    rows = terms_found([("C1", AMENDMENT), ("C2", ORIGINAL)], INFO, lambda doc_id: {})
    assert rows[0] == {
        "marker": "C1",
        "term": "Payment Period",
        "value": "45 days",
        "source": "§5.1, AMD1.pdf, p.1",
        "status": "In force since 2024-04-01",
        "status_kind": "in_force",
    }
    assert (rows[1]["value"], rows[1]["status"]) == ("30 days", "Replaced by C1")


def test_an_original_clause_changed_by_an_uncited_amendment_says_so():
    rows = terms_found([("C1", ORIGINAL)], INFO, lambda doc_id: {"5.1": "AMD1.pdf"})
    assert rows[0]["status"] == "Amended by AMD1.pdf" and rows[0]["status_kind"] == "amended"


def test_highlights_cover_the_whole_phrase_the_answer_relies_on():
    spans = highlight_spans(ORIGINAL.text, ["30"])
    assert [ORIGINAL.text[s:e] for s, e in spans] == ["thirty (30) days", "30"] or [
        ORIGINAL.text[s:e] for s, e in spans
    ] == ["thirty (30) days"]
    assert all(")" not in ORIGINAL.text[s:e].replace("(30)", "") for s, e in spans)


def test_clause_pages_carry_the_text_and_the_highlights_for_each_marker():
    checks = check_answer("Net 45 applies, 45 days [C1].", {"C1": AMENDMENT}, INFO)
    pages = clause_pages([("C1", AMENDMENT)], checks, INFO)
    page = pages["C1"]
    assert page["doc_title"] == "AMD1.pdf" and page["page"] == 1 and page["text"] == AMENDMENT.text
    assert page["highlights"] and AMENDMENT.text[page["highlights"][0][0] :].startswith("forty")


def test_key_figures_skip_clause_numbers_and_years():
    text = "3.1 Liability Cap. Section 6.1 applies from 2024. The cap is $40,000 per Shipment."
    assert key_figures(text) == ["$40,000 per Shipment"]
    assert key_figures("2.1 Notice. Either party may leave on ninety (90) days' notice.") == [
        "90 days"
    ]


def test_term_names_come_from_the_heading_or_a_named_section_reference():
    assert term_name(hit("x", "9.1 Required Cover. The Supplier shall insure.")) == "Required Cover"
    assert term_name(AMENDMENT) == "Payment Period"
    assert term_name(hit("y", "Plain text", clause_no="7.2")) == "Clause 7.2"
