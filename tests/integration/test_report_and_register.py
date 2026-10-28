import datetime as dt
import json

import pytest

from clausecheck.services import contracts_service as contracts
from clausecheck.services.insights_service import InsightsService
from clausecheck.store import sqlite as db
from clausecheck.store.query_log import QueryLog

NOW = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.UTC)


def log(q, qid, outcome, at, supplier="S-ACME", ms=2000, ttft=1000, citations=None, **extra):
    q.log(
        {
            "query_id": qid,
            "created_at": at,
            "question": extra.pop("question", "What are the payment terms?"),
            "supplier_id": supplier,
            "outcome": outcome,
            "latency_ms": ms,
            "ttft_ms": ttft,
            "citations": citations or [],
            **extra,
        }
    )


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "r.db")
    db.init_db(c)
    db.upsert_supplier(c, "S-ACME", "Acme Corp", [])
    db.upsert_supplier(c, "S-BETA", "Beta Industries", [])
    db.upsert_supplier(c, "S-EMPTY", "No Documents", [])  # a supplier with no document is hidden
    for doc_id, supplier, kind, date, title in [
        ("d1", "S-ACME", "contract", "2023-01-15", "ACME-MSA.pdf"),
        ("d2", "S-ACME", "amendment", "2024-03-01", "ACME-AMD1.pdf"),
        ("d3", "S-BETA", "contract", "2022-05-01", "BETA.pdf"),
    ]:
        db.upsert_document(
            c,
            {
                "doc_id": doc_id,
                "supplier_id": supplier,
                "doc_type": kind,
                "effective_date": date,
                "title": title,
                "ingested_at": "2026-10-27T18:40:00Z",
            },
        )
    return c


def seed(conn):
    q = QueryLog(conn)
    log(
        q,
        "a1",
        "answered",
        "2026-10-27T10:00:00Z",
        citations=["c1", "c2", "c3"],
        ms=3000,
        ttft=1500,
    )
    log(
        q,
        "a2",
        "answered",
        "2026-10-27T10:05:00Z",
        citations=["c1"],
        ms=4000,
        ttft=2500,
        unsupported=True,
    )
    log(
        q,
        "r1",
        "refused",
        "2026-10-27T10:10:00Z",
        supplier="S-BETA",
        question="Is there a most-favoured-nation clause?",
    )
    log(
        q,
        "e1",
        "error",
        "2026-10-27T10:15:00Z",
        error="groq: RateLimitError 429; gemini: error",
        ms=500,
        ttft=500,
    )
    log(
        q,
        "e2",
        "error",
        "2026-10-27T10:16:00Z",
        error="ClauseCheck couldn't generate an answer right now.",
        ms=500,
        ttft=500,
    )
    log(q, "old", "answered", "2026-10-01T10:00:00Z", ms=9000, ttft=9000)  # outside a 7-day window


# ---- the register -------------------------------------------------------------------------


def test_register_lists_contracts_with_documents_dates_and_last_check(conn):
    seed(conn)
    rows = {c["id"]: c for c in contracts.list_contracts(conn)}
    assert set(rows) == {"S-ACME", "S-BETA"}  # S-EMPTY has no document
    acme = rows["S-ACME"]
    assert acme["name"] == "Acme Corp" and acme["documents"] == 2
    assert acme["kinds"] == {"contract": 1, "amendment": 1}
    assert acme["latest_effective"] == "2024-03-01"
    assert acme["last_checked"] == "2026-10-27T10:16:00Z"  # the latest of its questions


def test_register_puts_the_most_recently_checked_first_and_unchecked_last(conn):
    q = QueryLog(conn)
    log(q, "b1", "answered", "2026-10-26T09:00:00Z", supplier="S-BETA")
    assert [c["id"] for c in contracts.list_contracts(conn)] == ["S-BETA", "S-ACME"]
    log(q, "a1", "answered", "2026-10-27T09:00:00Z", supplier="S-ACME")
    assert [c["id"] for c in contracts.list_contracts(conn)] == ["S-ACME", "S-BETA"]


def test_recent_checks_say_how_each_one_ended_in_words(conn):
    seed(conn)
    got = {c["query_id"]: c for c in contracts.recent_checks(conn, limit=10)}
    assert got["a1"]["outcome"] == "3 citations checked" and got["a1"]["kind"] == "checked"
    assert got["a2"]["outcome"] == "Verify before use" and got["a2"]["kind"] == "verify"
    assert got["r1"]["outcome"] == "No term found" and got["r1"]["kind"] == "none"
    assert got["e1"]["outcome"] == "System failure" and got["e1"]["kind"] == "failed"
    assert got["r1"]["contract"] == "Beta Industries"
    assert [c["query_id"] for c in contracts.recent_checks(conn, limit=2)] == ["e2", "e1"]
    only_beta = contracts.recent_checks(conn, contract_id="S-BETA")
    assert [c["query_id"] for c in only_beta] == ["r1"]


def test_common_questions_are_the_most_asked_answered_ones(conn):
    q = QueryLog(conn)
    for i in range(3):
        log(
            q,
            f"p{i}",
            "answered",
            f"2026-10-27T10:0{i}:00Z",
            question="What are the payment terms?",
        )
    log(q, "n1", "answered", "2026-10-27T11:00:00Z", question="Who are the parties?")
    log(q, "n2", "refused", "2026-10-27T11:05:00Z", question="Is there an MFN clause?")
    assert contracts.common_questions(conn, "S-ACME") == [
        "What are the payment terms?",
        "Who are the parties?",
    ]


# ---- the report ---------------------------------------------------------------------------


def rows_by_key(report):
    return {r["key"]: r for r in report["scorecard"]}


def test_the_answer_rate_counts_system_failures_as_not_answered(conn, tmp_path):
    seed(conn)
    report = InsightsService(conn).report(days=7, now=NOW, results_dir=tmp_path)
    rate = rows_by_key(report)["answered_rate"]
    assert report["questions"] == 5 and report["outcomes"] == {
        "answered": 2,
        "refused": 1,
        "error": 2,
    }
    assert rate["value"] == pytest.approx(2 / 5)  # errors are in the denominator
    assert rate["status"] == "below" and rate["basis"] == "2 of 5 questions, errors included"
    assert any("excluding them it would be 67%" in n for n in report["notes"])


def test_each_target_has_a_status_and_the_headline_states_the_result(conn, tmp_path):
    seed(conn)
    report = InsightsService(conn).report(days=7, now=NOW, results_dir=tmp_path)
    by_key = rows_by_key(report)
    # time to first words: 500, 500, 1000, 1500 and 2500 ms, so the median is 1000
    assert by_key["ttft_ms"]["value"] == 1000 and by_key["ttft_ms"]["status"] == "met"
    assert (
        by_key["checked_ms"]["value"] == 3500
        and by_key["checked_ms"]["basis"] == "Median of 2 answers"
    )
    assert by_key["citation_accuracy"]["status"] == "not_measured"
    assert report["headline"].startswith("Two of three measured targets were met.")
    assert "citation accuracy has not yet been measured" in report["headline"]


def test_the_window_and_the_contract_filter_the_figures(conn, tmp_path):
    seed(conn)
    service = InsightsService(conn)
    assert service.report(days=7, now=NOW, results_dir=tmp_path)["questions"] == 5
    everything = service.report(days=None, now=NOW, results_dir=tmp_path)
    assert everything["questions"] == 6 and everything["window"]["label"] == "All time"
    beta = service.report(days=7, contract_id="S-BETA", now=NOW, results_dir=tmp_path)
    assert beta["questions"] == 1 and beta["contract"] == "Beta Industries"


def test_citation_accuracy_is_read_from_the_newest_held_out_run_only(conn, tmp_path):
    seed(conn)
    (tmp_path / "2026-10-20_e2e_tune.json").write_text(
        json.dumps({"metrics": {"citation_accuracy": 0.99}})
    )
    service = InsightsService(conn)
    assert (
        rows_by_key(service.report(now=NOW, results_dir=tmp_path))["citation_accuracy"]["value"]
        is None
    )
    (tmp_path / "2026-10-25_e2e_heldout.json").write_text(
        json.dumps({"metrics": {"citation_accuracy": 0.93}})
    )
    row = rows_by_key(service.report(now=NOW, results_dir=tmp_path))["citation_accuracy"]
    assert row["value"] == 0.93 and row["status"] == "met" and "2026-10-25" in row["basis"]


def test_failures_are_listed_by_cause_and_old_ones_say_the_cause_was_not_recorded(conn, tmp_path):
    seed(conn)
    failures = InsightsService(conn).report(now=NOW, results_dir=tmp_path)["failures"]
    assert {f["cause"]: f["count"] for f in failures} == {
        "groq: RateLimitError 429; gemini: error": 1,
        "Cause not recorded": 1,
    }


def test_unanswered_questions_are_listed_newest_first_with_their_outcome(conn, tmp_path):
    seed(conn)
    unanswered = InsightsService(conn).report(now=NOW, results_dir=tmp_path)["unanswered"]
    assert [u["outcome"] for u in unanswered] == [
        "System failure",
        "System failure",
        "No term found",
    ]
    assert unanswered[2]["contract"] == "Beta Industries"


def test_a_window_with_no_questions_has_no_numbers_and_says_so(conn, tmp_path):
    report = InsightsService(conn).report(days=7, now=NOW, results_dir=tmp_path)
    assert report["questions"] == 0 and rows_by_key(report)["answered_rate"]["value"] is None
    assert report["headline"].startswith("No target could be measured")


def test_the_index_figures_come_from_the_documents(conn, tmp_path):
    index = InsightsService(conn).report(now=NOW, results_dir=tmp_path)["index"]
    assert index == {"contracts": 2, "documents": 3, "last_indexed": "2026-10-27T18:40:00Z"}
