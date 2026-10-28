"""The pure parts of the redesigned frontend: formatting, check records, filing, HTML builders."""

import datetime as dt

from components import format as fmt
from components import ui
from components.api_client import ApiUnavailable
from components.checks import record_from_events
from components.contracts import file_document, slugify, too_big, valid_date

from tests.frontend.conftest import CHECKS

NOW = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.UTC)


def test_numbers_are_written_for_people():
    assert fmt.seconds(2300) == "2.3 s"
    assert fmt.percent(0.683) == "68%"
    assert fmt.plural(1, "clause") == "1 clause"
    assert fmt.plural(3, "clause") == "3 clauses"
    assert fmt.possessive("Helixa Cloud Systems") == "Helixa Cloud Systems’"
    assert fmt.possessive("Orion") == "Orion’s"


def test_slugify_and_dates():
    assert slugify("Q3 Supply Deal (2025)") == "q3-supply-deal-2025"
    assert slugify("???") == ""
    assert valid_date("") and valid_date("2024-04-01")
    assert not valid_date("1 April 2024") and not valid_date("2024-4-1")


def test_a_file_over_the_limit_gets_our_own_wording():
    assert too_big("a.pdf", 1024) is None
    message = too_big("big.pdf", 21 * 1024 * 1024)
    assert "big.pdf" in message and "20 MB" in message


def test_record_kinds_follow_the_events():
    done = ("done", {"outcome": "answered", "timings": {}})
    checked = record_from_events("q", [("checks", CHECKS), done], "t")
    assert checked["kind"] == "checked" and checked["terms"] == CHECKS["terms"]
    verify = record_from_events("q", [("checks", {**CHECKS, "status": "verify"}), done], "t")
    assert verify["kind"] == "verify"
    plain = record_from_events("q", [("token", {"text": "Hi"}), done], "t")
    assert plain["kind"] == "plain" and plain["text"] == "Hi"
    refused = record_from_events(
        "q", [("done", {"outcome": "refused", "refusal_reason": "x"})], "t"
    )
    assert refused["kind"] == "none" and refused["message"] is None
    other = record_from_events(
        "q",
        [
            ("token", {"text": "That is another contract."}),
            ("done", {"outcome": "refused", "refusal_reason": "other_contract"}),
        ],
        "t",
    )
    assert other["message"] == "That is another contract."
    assert record_from_events("q", [("token", {"text": "x"})], "t")["kind"] == "failed"
    assert record_from_events("q", [("error", {}), done], "t")["kind"] == "failed"


class Api:
    def __init__(self, upload=None, jobs=()):
        self._upload, self._jobs, self.calls = upload, list(jobs), []

    def upload(self, *args):
        self.calls.append(args)
        if isinstance(self._upload, Exception):
            raise self._upload
        return self._upload

    def job(self, job_id):
        return self._jobs.pop(0)


def _file(api, **kw):
    return list(file_document(api, "a.pdf", b"x", "c1", "contract", sleep=lambda s: None, **kw))


def test_filing_follows_the_job_to_its_end():
    api = Api(
        {"job_id": "j"}, [{"status": "running", "steps": []}, {"status": "done", "steps": []}]
    )
    events = _file(api, effective_date="2024-04-01", amends="doc-a")
    assert [d["status"] for _, d in events] == ["running", "done"]
    assert api.calls[0][-2:] == ("2024-04-01", "doc-a")


def test_filing_reports_each_way_it_can_stop():
    assert _file(Api({"duplicate": True, "doc_id": "d"})) == [("duplicate", {"doc_id": "d"})]
    assert _file(Api(ValueError("too large")))[0] == ("rejected", {"message": "too large"})
    assert _file(Api(ApiUnavailable("down")))[0][0] == "error"
    failed = _file(Api({"job_id": "j"}, [{"status": "failed", "steps": []}]))
    assert failed[-1][1]["status"] == "failed"
    timeout = list(
        file_document(
            Api({"job_id": "j"}, [{"status": "running", "steps": []}] * 3),
            "a.pdf",
            b"x",
            "c1",
            "contract",
            timeout=-1,
            sleep=lambda s: None,
        )
    )
    assert timeout[-1][1]["status"] == "timeout"


def test_the_seal_lists_only_what_was_verified():
    sealed = ui.seal(CHECKS)
    assert "Checked" in sealed and "1 of 1 citations found" in sealed
    assert "1 of 1 numbers match" in sealed
    verify = {
        **CHECKS,
        "status": "verify",
        "numbers": {"matched": 0, "total": 1, "unverified": [{"value": "60 days", "marker": "C1"}]},
    }
    assert "Verify" in ui.seal(verify) and "not found: “60 days”" in ui.seal(verify)
    assert "does not appear in C1" in ui.verify_note(verify)
    assert ui.verify_note(CHECKS) == ""


def test_answers_bold_figures_and_mark_citations_without_raw_markers():
    out = ui.answer_html("Due within 45 days [C1] <script>")
    assert "<b>45 days</b>" in out and "[C1]" not in out and "<script>" not in out


def test_the_failure_note_is_never_worded_as_a_finding():
    assert "System failure, not a finding" in ui.failed_note()
    assert "Nothing was guessed" in ui.none_note("Orion", 2, None)


def test_working_record_shows_real_steps_not_a_spinner():
    steps = {"found": {"id": "found", "state": "done", "clauses": 3, "documents": 2, "ms": 400}}
    html = ui.working_record("When?", "Orion", steps)
    assert "Found 3 clauses in 2 Orion documents" in html and "0.4 s" in html
    assert "Writing the answer" in html and "Checking every citation" in html


def test_status_line_says_not_measured_for_citation_accuracy():
    from tests.frontend.conftest import REPORT

    line = ui.status_line(REPORT)
    assert "Citation accuracy <b>not measured</b>" in line and "Questions <b>603</b>" in line
