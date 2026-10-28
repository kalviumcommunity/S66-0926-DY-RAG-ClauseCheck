"""Insights: the service report. One sentence that states the result, then the evidence."""

import csv
import datetime as dt
import io

import streamlit as st
from components import format as fmt
from components import ui
from components.contracts import list_contracts
from components.layout import frame
from components.state import init_state

WINDOWS = {"Last 7 days": "7", "Last 30 days": "30", "All time": "all"}

api = init_state()
frame(api, "insights")
contracts = list_contracts(api)
names = {c["id"]: c["name"] for c in contracts}

head, window_box, contract_box, download_box = st.columns(
    [5, 1.6, 1.8, 1.3], vertical_alignment="bottom"
)
window = window_box.selectbox(
    "Window", list(WINDOWS), key="report-window", label_visibility="collapsed"
)
choice = contract_box.selectbox(
    "Contract",
    ["All contracts", *names.values()],
    key="report-contract",
    label_visibility="collapsed",
)
contract_id = next((cid for cid, n in names.items() if n == choice), None)

try:
    report = api.report(WINDOWS[window], contract_id)
except Exception:
    report = None

today = dt.datetime.now().astimezone()
head.html(
    ui.docket(
        f"Service report · {today:%A} {today.day} {today:%B %Y} · "
        f"{'all contracts' if contract_id is None else choice}",
        "How ClauseCheck performed",
    )
)

if report is None:
    st.html(ui.backend_down())
    st.stop()

basis = (
    f"Based on {fmt.plural(report['questions'], 'logged question')} "
    f"({report['window']['label'].lower()})."
    if report["questions"]
    else "There are no logged questions in this window."
)
st.html(f'<div class="cc-headline">{ui.esc(report["headline"])} <span>{ui.esc(basis)}</span></div>')
st.html(ui.scorecard(report))

first, second = st.columns(2, gap="large")
with first:
    st.html(
        '<div class="cc-figure">Figure 1</div><div class="cc-fig-title">What happened to each question</div>'
    )
    st.html(ui.outcome_figure(report))
    if report["days_with_data"] < 3:
        st.html(
            '<div class="cc-fine">A daily trend appears once there are three days of data.</div>'
        )
with second:
    st.html(
        '<div class="cc-figure">Figure 2</div><div class="cc-fig-title">Questions by topic</div>'
    )
    st.html(ui.topic_figure(report))

st.html(
    '<div class="cc-figure">Table 2</div><div class="cc-fig-title">Questions without an answer, latest first</div>'
)
st.html(ui.unanswered_table(report))
st.html(ui.footnotes(report))


def as_csv(report: dict) -> str:
    """The numbers on this page as CSV, so a reviewer can check them."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["section", "name", "value", "target", "status", "basis"])
    for row in report["scorecard"]:
        writer.writerow(
            ["scorecard", row["label"], row["value"], row["target"], row["status"], row["basis"]]
        )
    for key, count in report["outcomes"].items():
        writer.writerow(["outcome", key, count, "", "", ""])
    for topic in report["topics"]:
        writer.writerow(["topic", topic["topic"], topic["count"], "", "", ""])
    return out.getvalue()


download_box.download_button(
    "Download CSV",
    as_csv(report),
    file_name=f"clausecheck-report-{report['generated_at'][:10]}.csv",
    mime="text/csv",
)
