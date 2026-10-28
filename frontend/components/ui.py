"""The distinctive parts of the interface, as HTML strings.

Streamlit supplies inputs and state; everything you can see that is not an input is written here, so
it does not look like a stock Streamlit app. Every value that comes from a user, a document or the
backend goes through `esc` before it is placed in markup.
"""

import re
from html import escape as esc

from components import format as fmt

CITE_RE = re.compile(r"\[C(\d+)\]")
FIGURE_RE = re.compile(
    r"(\$?\d[\d,]*(?:\.\d+)?\)?\s?(?:%|(?:calendar |business )?(?:days?|weeks?|months?|years?|hours?"
    r"|minutes?)\b|per [A-Za-z]+))",
    re.I,
)
SEAL_OK, SEAL_WARN = "✓", "⚠"


def answer_html(text: str) -> str:
    """The answer with figures in bold and `[C1]` as a small green `c1` reference."""
    out = esc(text or "")
    out = FIGURE_RE.sub(r"<b>\1</b>", out)
    return CITE_RE.sub(lambda m: f'<span class="cc-cite">c{m.group(1)}</span>', out)


def cite(marker: str) -> str:
    return f'<span class="cc-cite">{esc(marker.lower())}</span>'


# ---- masthead and status line ------------------------------------------------------------------


def wordmark() -> str:
    return '<div class="cc-wordmark"><span>§</span>ClauseCheck</div>'


def index_status(health: dict | None, last_indexed: str | None) -> str:
    """Top right: whether the index is ready, its size, and when it was last built."""
    if not health:
        return '<div class="cc-index"><b>Index unavailable</b> · the backend is not answering</div>'
    ready = health.get("status") == "ok"
    state = "Index current" if ready else "Index incomplete"
    size = (
        f"{fmt.plural(health.get('suppliers', 0), 'contract')} · "
        f"{fmt.plural(health.get('documents', 0), 'document')}"
    )
    last = f"Last indexed {fmt.long_when(last_indexed)} · " if last_indexed else ""
    return (
        f'<div class="cc-index"><b>{state}</b> · {esc(size)}<br>'
        f"{esc(last)}answers quote contracts, not legal advice</div>"
    )


def backend_down() -> str:
    """Shown on every page when the backend cannot be reached: red, and not worded as a finding."""
    return (
        '<div class="cc-note cc-note--failed"><b>⊗ System failure, not a finding.</b> ClauseCheck '
        "cannot reach its backend, so no contract can be checked right now. Nothing was lost; "
        "start the backend and reload this page.</div>"
    )


def double_rule() -> str:
    return '<div class="cc-double-rule"></div>'


def _flag(row: dict, shown: str) -> str:
    """`⚠ target 80%` or `✓ target 30 s`, in the colour of its status."""
    met = row["status"] == "met"
    mark, css = (SEAL_OK, "cc-met") if met else (SEAL_WARN, "cc-below")
    arrow = "≥" if row["direction"] == "min" else "<" if row["key"] == "ttft_ms" else "≤"
    return f'<span class="cc-flag {css}">{mark} target {arrow} {esc(shown)}</span>'


def status_line(report: dict) -> str:
    """The five numbers and their targets as one ruled line of text under the masthead."""
    by_key = {r["key"]: r for r in report["scorecard"]}
    rate, ttft, checked = by_key["answered_rate"], by_key["ttft_ms"], by_key["checked_ms"]
    accuracy = by_key["citation_accuracy"]
    cells = [f"{esc(report['window']['label'])}"]
    cells.append(f"Questions <b>{report['questions']}</b>")
    if rate["value"] is None:
        cells.append('<span class="cc-na">No questions yet</span>')
    else:
        cells.append(
            f"Answered <b>{fmt.percent(rate['value'])}</b> "
            + _flag(rate, fmt.percent(rate["target"]))
        )
        cells.append(
            f"First words <b>{fmt.seconds(ttft['value'])}</b> "
            + _flag(ttft, fmt.seconds(ttft["target"]))
        )
        cells.append(
            f"Checked <b>{fmt.seconds(checked['value'])}</b> "
            + _flag(checked, fmt.seconds(checked["target"]))
        )
    shown = "not measured" if accuracy["value"] is None else fmt.percent(accuracy["value"])
    cells.append(f"Citation accuracy <b>{shown}</b>")
    return '<div class="cc-status">' + "".join(f"<div>{c}</div>" for c in cells) + "</div>"


# ---- docket, register, recent checks ------------------------------------------------------------


def docket(kicker: str, title: str, ids: list[str] | None = None) -> str:
    chips = f'<span class="cc-ids">{esc(" · ".join(ids))}</span>' if ids else ""
    return (
        f'<div class="cc-kicker">{esc(kicker)}</div>'
        f'<div class="cc-title">{esc(title)}{chips}</div>'
    )


def register_head() -> str:
    return (
        '<div class="cc-reg-head"><div>No.</div><div>Contract</div><div>Documents</div>'
        "<div>Latest effective</div><div>Last checked</div></div>"
    )


def register_row(no: int, contract: dict) -> str:
    return (
        '<div class="cc-reg-row">'
        f'<div class="cc-no">{no:03d}</div>'
        f'<div class="cc-reg-name">{esc(contract["name"])}</div>'
        f"<div>{esc(fmt.kinds(contract['kinds']))}</div>"
        f'<div class="cc-date">{esc(fmt.day(contract["latest_effective"]))}</div>'
        f"<div>{esc(fmt.when(contract['last_checked']))}</div></div>"
    )


def documents_list(docs: list[dict]) -> str:
    """A contract's files: title, kind, date, and which file an amendment changes."""
    if not docs:
        return '<div class="cc-fine">This contract has no documents yet.</div>'
    titles = {d["doc_id"]: d.get("title") or d["doc_id"] for d in docs}
    rows = []
    for d in sorted(docs, key=lambda d: (d.get("effective_date") or "", d.get("title") or "")):
        kind = "Amendment" if d.get("doc_type") == "amendment" else "Contract"
        if d.get("doc_type") in ("price_schedule", "certificate"):
            kind = fmt.kinds({d["doc_type"]: 1})
        extra = (
            f"effective {fmt.day(d.get('effective_date'))}"
            if d.get("effective_date")
            else "no date"
        )
        if d.get("parent_doc_id"):
            extra += f" · amends {titles.get(d['parent_doc_id'], d['parent_doc_id'])}"
        elif d.get("doc_type") == "amendment":
            extra += " · not linked to an agreement"
        rows.append(
            f'<div class="cc-recent"><span class="cc-date">{esc(d.get("title") or d["doc_id"])}</span>'
            f"<small>{esc(kind)} · {esc(extra)}</small></div>"
        )
    return "".join(rows)


def recent_checks(rows: list[dict]) -> str:
    if not rows:
        return (
            '<div class="cc-side-title">Recent checks</div>'
            '<div class="cc-fine">Nothing has been checked yet. Choose a contract and ask '
            "a question; every check is listed here with its outcome.</div>"
        )
    items = "".join(
        f'<div class="cc-recent"><q>{esc(r["question"])}</q>'
        f"<small>{esc(r['contract'])} · "
        f'<span class="cc-out-{esc(r["kind"])}">{esc(r["outcome"])}</span></small></div>'
        for r in rows
    )
    return (
        '<div class="cc-side-title">Recent checks</div>'
        + items
        + '<div class="cc-fine">Every check is logged with its sources, so an answer can be '
        "traced later.</div>"
    )


# ---- a check record ----------------------------------------------------------------------------


def terms_table(terms: list[dict]) -> str:
    if not terms:
        return ""
    rows = []
    for t in terms:
        value = esc(t["value"])
        term = esc(t["term"])
        if t["status_kind"] == "replaced":
            value = f'<span class="cc-strike">{value}</span>'
            term += ", original"
        rows.append(
            f"<tr><td>{term}</td><td>{value}</td>"
            f"<td>{cite(t['marker'])} {esc(t['source'])}</td>"
            f'<td><span class="cc-tag cc-tag--{esc(t["status_kind"])}">{esc(t["status"])}</span></td></tr>'
        )
    return (
        '<div class="cc-h">Terms found</div><table class="cc-t"><thead><tr><th>Term</th>'
        "<th>Value in the clause</th><th>Source</th><th>Status</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _amendment_line(a: dict) -> str:
    where = f"§{a['clause_no']}" if a.get("clause_no") else "a clause"
    line = f"Amendment applied: {a['title']} ({where})"
    if a.get("replaces_clause"):
        line += f" replaces §{a['replaces_clause']}"
    return line


def seal(checks: dict) -> str:
    """The seal and the lines under it: only what the backend verified, never the model's words."""
    cit, num = checks["citations"], checks["numbers"]
    ok = checks["status"] == "checked"
    lines = [
        (
            cit["found"] == cit["total"],
            f"{cit['found']} of {cit['total']} citations found in the documents",
        )
    ]
    if num["total"]:
        if num["unverified"]:
            missing = ", ".join(f"“{u['value']}”" for u in num["unverified"])
            lines.append(
                (False, f"{num['matched']} of {num['total']} numbers match; not found: {missing}")
            )
        else:
            lines.append(
                (True, f"{num['matched']} of {num['total']} numbers match the clause text")
            )
    else:
        lines.append((True, "No figures in the answer to check"))
    if checks.get("uncited_sentences"):
        lines.append(
            (False, fmt.plural(checks["uncited_sentences"], "sentence") + " without a citation")
        )
    lines += [(True, _amendment_line(a)) for a in checks.get("amendments", [])]
    items = "".join(
        f"<li>{SEAL_OK if good else SEAL_WARN} {esc(text)}</li>" for good, text in lines
    )
    word = "Checked" if ok else "Verify"
    css = "" if ok else " cc-seal--verify"
    return f'<div class="cc-seal{css}"><div class="cc-seal-word">{word}</div><ul>{items}</ul></div>'


def verify_note(checks: dict) -> str:
    """The amber note for an answer that did not pass every check."""
    unverified = checks["numbers"]["unverified"]
    if not unverified:
        return ""
    first = unverified[0]
    where = first["marker"] if first.get("marker") else "any cited clause"
    more = f" (and {len(unverified) - 1} more)" if len(unverified) > 1 else ""
    return (
        f'<div class="cc-note cc-note--verify"><b>{SEAL_WARN} '
        f"{fmt.plural(len(unverified), 'number')} not verified.</b> “{esc(first['value'])}” does not "
        f"appear in {esc(where)}{more}. Read the clause before relying on it.</div>"
    )


def none_note(contract: str, documents: int, message: str | None = None) -> str:
    """Nothing was found: grey, and it says nothing was guessed."""
    if message:  # for example the other-contract refusal, whose wording the backend owns
        return f'<div class="cc-note cc-note--none">⊖ {esc(message)}</div>'
    return (
        '<div class="cc-note cc-note--none"><b>⊖ No term found.</b> '
        f"{esc(fmt.possessive(contract))} {esc(fmt.plural(documents, 'document'))} do not contain "
        "this. "
        "Nothing was guessed.</div>"
    )


def failed_note() -> str:
    """A system failure is red and never worded like a finding."""
    return (
        '<div class="cc-note cc-note--failed"><b>⊗ System failure, not a finding.</b> The language '
        "model did not respond, so nothing was written. Your question is kept.</div>"
    )


def check_record(rec: dict, number: int, contract: str, documents: int) -> str:
    """One finished check: question, answer, terms, and how it ended."""
    head = (
        f'<div class="cc-meta">Check {number} · asked {esc(fmt.short_clock(rec.get("asked_at")))}</div>'
        f'<div class="cc-q">{esc(rec["question"])}</div>'
    )
    kind = rec["kind"]
    if kind == "failed":
        return head + failed_note()
    if kind == "none":
        return head + none_note(contract, documents, rec.get("message"))
    if kind == "plain":  # an older backend: the answer, but nothing was verified, so no seal
        return (
            head
            + f'<div class="cc-answer">{answer_html(rec.get("text", ""))}</div>'
            + '<div class="cc-note cc-note--verify"><b>⚠ Not checked.</b> This backend did not send '
            "its checks, so the answer is shown without the seal. Read the clause before relying "
            "on it.</div>"
        )
    checks = rec["checks"]
    timing = rec.get("timings") or {}
    foot = ""
    if rec.get("cached"):
        foot = (
            '<div class="cc-timing">Served from an earlier check of this question; '
            "its checks were kept with it.</div>"
        )
    elif timing.get("ttft") is not None:
        foot = (
            f'<div class="cc-timing">First words after {fmt.seconds(timing["ttft"])} · '
            f'checked after {fmt.seconds(timing["total"])}</div>'
        )
    return (
        head
        + f'<div class="cc-answer">{answer_html(checks["answer"])}</div>'
        + terms_table(rec.get("terms", []))
        + seal(checks)
        + verify_note(checks)
        + foot
    )


def working_record(question: str, contract: str, steps: dict) -> str:
    """While a check runs: the real pipeline steps with their timings, not a spinner."""
    found = steps.get("found")
    write = steps.get("write", {})
    check = steps.get("check", {})

    def row(state: str, text: str, ms=None) -> str:
        icon = {"done": SEAL_OK, "active": "◐", "todo": "○"}[state]
        timing = f"<code>{fmt.seconds(ms)}</code>" if ms is not None else ""
        return f'<li class="{state}">{icon} {esc(text)}{timing}</li>'

    items = []
    if found and found.get("cached"):
        items.append(row("done", "Repeating an earlier check of this question"))
    elif found:
        docs = fmt.plural(found["documents"], contract + " document", contract + " documents")
        items.append(
            row(
                "done", f"Found {fmt.plural(found['clauses'], 'clause')} in {docs}", found.get("ms")
            )
        )
    else:
        items.append(row("active", f"Searching {contract}’s documents"))
    wstate = write.get("state", "todo" if not found else "active")
    items.append(row(wstate, "Writing the answer from those clauses only", write.get("ms")))
    items.append(row(check.get("state", "todo"), "Checking every citation and number"))
    return (
        f'<div class="cc-meta">Working</div><div class="cc-q">{esc(question)}</div>'
        f'<ul class="cc-steps">{"".join(items)}</ul>'
    )


# ---- the clause as a page -----------------------------------------------------------------------


def highlighted(text: str, spans: list[list[int]]) -> str:
    """`text` escaped, with the given character ranges wrapped in <mark>."""
    out, cursor = [], 0
    for start, end in sorted(spans):
        if start < cursor or end > len(text):
            continue
        out.append(esc(text[cursor:start]))
        out.append(f"<mark>{esc(text[start:end])}</mark>")
        cursor = end
    out.append(esc(text[cursor:]))
    return "".join(out)


def sheet(clause: dict | None, marker: str | None) -> str:
    """The cited clause as one annotated page, with the words the answer relies on marked."""
    if not clause:
        return (
            '<div class="cc-sheet"><div class="cc-sheet-empty">The clause an answer cites appears '
            "here, on its page, with the words it relies on highlighted.</div></div>"
        )
    kind = "Amendment" if clause.get("doc_type") == "amendment" else "Contract"
    effective = clause.get("effective_date")
    sub = f"{kind}" + (f" · effective {esc(fmt.day(effective))}" if effective else "")
    where = f"§{clause['clause_no']}" if clause.get("clause_no") else (clause.get("section") or "")
    page = f"page {clause['page']}" if clause.get("page") else ""
    spans = clause.get("highlights") or []
    foot = (
        "Highlighted: the exact words the answer relies on"
        if spans
        else "No figure from the answer appears in this clause"
    )
    return (
        '<div class="cc-sheet">'
        f'<div class="cc-sheet-head"><span>{esc(clause.get("doc_title") or "")}</span>'
        f"<span>{esc(page)}</span></div>"
        f'<div class="cc-sheet-sub">{sub} · {esc(where)}</div>'
        f'<div class="cc-clause"><span class="cc-margin">{esc((marker or "").lower())} →</span>'
        f'{highlighted(clause.get("text") or "", spans)}</div>'
        f'<div class="cc-sheet-foot">{foot}</div></div>'
    )


# ---- the filing log (Add a contract) -------------------------------------------------------------

FILING_STEPS = ["checked", "extracted", "split", "embedding", "ready"]
FILING_LABELS = {
    "checked": "File checked",
    "extracted": "Text extracted",
    "split": "Split into clauses",
    "embedding": "Embedding clauses",
    "ready": "Ready to check",
}


def filing_log(title: str, steps: list[dict], failed: bool = False) -> str:
    """Each indexing step with its time and real count. Steps not reached yet are shown dimmed."""
    done = {s["id"]: s for s in steps}
    rows = []
    active_set = False
    for step_id in FILING_STEPS:
        step = done.get(step_id)
        if step:
            rows.append(
                f'<div class="cc-log-row"><span class="t">{esc(fmt.clock(step["at"]))}</span>'
                f'<span class="ok">{SEAL_OK}</span><span>{esc(step["label"])}'
                f'<small>{esc(step["detail"])}</small></span></div>'
            )
        elif failed:
            continue
        else:
            icon = "◐" if not active_set else "○"
            active_set = True
            rows.append(
                f'<div class="cc-log-row todo"><span class="t"></span><span>{icon}</span>'
                f"<span>{esc(FILING_LABELS[step_id])}</span></div>"
            )
    if failed:
        bad = done.get("failed", {})
        rows.append(
            '<div class="cc-log-row"><span class="t"></span><span class="bad">⊗</span>'
            f'<span class="bad">{esc(bad.get("label", "Could not be filed"))}'
            f'<small>{esc(bad.get("detail", ""))}</small></span></div>'
        )
    return (
        f'<div class="cc-log-title">Filing log</div><div class="cc-kicker" style="margin-top:2px">'
        f"{esc(title)}</div>{''.join(rows)}"
        '<div class="cc-fine">If any step fails, nothing from this filing enters the index.</div>'
    )


def warning_note(message: str) -> str:
    """A problem with what was typed or chosen, in amber: it can be fixed and tried again."""
    return f'<div class="cc-note cc-note--verify"><b>{SEAL_WARN} {esc(message)}</b></div>'


def filed_line(filed: dict) -> str:
    """The last filing in this session, with its real counts."""
    return (
        f'<div class="cc-fine" style="margin-top:18px"><span class="cc-met">{SEAL_OK}</span> '
        f"<b>{esc(filed['name'])}</b> filed · {esc(fmt.plural(filed['documents'], 'document'))} · "
        f"{esc(fmt.plural(filed['clauses'], 'clause'))} · {esc(fmt.short_clock(filed['at']))}</div>"
    )


def filing_idle() -> str:
    """The filing log before anything is filed: says what will appear, not a blank area."""
    return (
        '<div class="cc-log-title">Filing log</div>'
        '<div class="cc-fine">Nothing is being filed. When you file a document, each step of '
        "indexing appears here with its time and its real counts: file checked, text extracted, "
        "split into clauses, embedded, ready.</div>"
    )


def step_heading(no: int, name: str, hint: str = "") -> str:
    hint_html = f'<div class="cc-hint">{esc(hint)}</div>' if hint else ""
    return (
        f'<div class="cc-step"><div class="cc-step-no">{no}</div>'
        f'<div><div class="cc-step-name">{esc(name)}</div>{hint_html}</div></div>'
    )


# ---- the report (Insights) ----------------------------------------------------------------------

STATUS_WORDS = {
    "met": ("✓ Met", "cc-met"),
    "below": ("⚠ Below target", "cc-below"),
    "above": ("⚠ Above target", "cc-below"),
    "not_measured": ("No evaluation run", "cc-na"),
    "context": ("For context", "cc-na"),
}


def _result(row: dict) -> str:
    key, value = row["key"], row["value"]
    if value is None:
        return "Not measured"
    return (
        fmt.percent(value) if key in ("answered_rate", "citation_accuracy") else fmt.seconds(value)
    )


def _target(row: dict) -> str:
    key, target = row["key"], row["target"]
    shown = (
        fmt.percent(target)
        if key in ("answered_rate", "citation_accuracy")
        else fmt.seconds(target)
    )
    sign = "≥" if row["direction"] == "min" else "<" if key == "ttft_ms" else "≤"
    return f"{sign} {shown}"


def _meter(row: dict) -> str:
    value, target = row["value"], row["target"]
    if value is None:
        return ""
    span = target * (1.25 if row["direction"] == "min" else 1.5)
    width = min(value / span, 1) * 100
    color = "var(--green)" if row["status"] == "met" else "var(--amber)"
    return (
        f'<div class="cc-meter"><i style="width:{width:.0f}%;background:{color}"></i>'
        f'<b style="left:{target / span * 100:.0f}%"></b></div>'
    )


def scorecard(report: dict) -> str:
    rows = []
    for row in report["scorecard"]:
        words, css = STATUS_WORDS[row["status"]]
        rows.append(
            f"<tr><td>{esc(row['label'])}</td><td><b>{esc(_result(row))}</b></td>"
            f"<td>{esc(_target(row))}</td><td>{_meter(row)}</td>"
            f'<td class="{css}">{words}</td><td>{esc(row["basis"])}</td></tr>'
        )
    rows.append(
        f"<tr><td>Questions asked</td><td><b>{report['questions']}</b></td><td>none</td><td></td>"
        '<td class="cc-na">For context</td><td>Questions in this window</td></tr>'
    )
    return (
        '<table class="cc-t"><thead><tr><th>Measure</th><th>Result</th><th>Target</th>'
        "<th>Against target</th><th>Status</th><th>Basis</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def outcome_figure(report: dict) -> str:
    total = report["questions"]
    outcomes = report["outcomes"]
    parts = [
        ("answered", "Answered with checked sources", "var(--green)"),
        ("refused", "No term found in the contract", "#ABA394"),
        ("error", "System failure", "var(--red)"),
    ]
    if not total:
        return '<div class="cc-fine">No questions were asked in this window.</div>'
    bar = "".join(
        f'<i style="width:{outcomes[k] / total * 100:.2f}%;background:{color}"></i>'
        for k, _, color in parts
        if outcomes[k]
    )
    keys = "".join(
        f'<div class="cc-key"><span class="sw" style="background:{color}"></span><span>{esc(label)}</span>'
        f'<span class="cc-no">{outcomes[k]}</span><span class="cc-no">{outcomes[k] / total * 100:.1f}%</span></div>'
        for k, label, color in parts
    )
    return f'<div class="cc-bar">{bar}</div>{keys}'


def topic_figure(report: dict) -> str:
    topics = report["topics"]
    if not topics:
        return '<div class="cc-fine">No questions were asked in this window.</div>'
    top = max(t["count"] for t in topics)
    rows = []
    for t in topics:
        hatched = " hatched" if t["topic"] == "Not classified" else ""
        rows.append(
            f'<div class="cc-topic"><span>{esc(t["topic"])}</span>'
            f'<span><div class="bar{hatched}" style="width:{t["count"] / top * 100:.0f}%"></div></span>'
            f'<span class="n">{t["count"]}</span></div>'
        )
    warn = ""
    if report["unclassified_share"] > 0.2:
        warn = (
            f'<div class="cc-fine {"cc-below"}">{SEAL_WARN} '
            f"{round(report['unclassified_share'] * 100)}% of questions match no topic; the topic "
            "list needs new categories (note 2).</div>"
        )
    return "".join(rows) + warn


def unanswered_table(report: dict) -> str:
    rows = report["unanswered"]
    if not rows:
        return '<div class="cc-fine">Every question in this window was answered.</div>'
    body = "".join(
        f'<tr><td class="cc-date">{esc(fmt.short_clock(r["at"]))}</td><td>{esc(r["contract"])}</td>'
        f"<td>“{esc(r['question'])}”</td>"
        f'<td class="cc-out-{esc(r["kind"])}">{esc(r["outcome"])}</td></tr>'
        for r in rows
    )
    return (
        '<table class="cc-t"><thead><tr><th>Time</th><th>Contract</th><th>Question</th>'
        f"<th>Outcome</th></tr></thead><tbody>{body}</tbody></table>"
    )


def footnotes(report: dict) -> str:
    notes = list(report["notes"])
    if report["failures"]:
        causes = "; ".join(f"{f['cause']} ({f['count']})" for f in report["failures"])
        notes.append(f"System failures by cause: {causes}.")
    items = " ".join(f"({i}) {esc(n)}" for i, n in enumerate(notes, 1))
    return f'<div class="cc-footnotes"><b>Notes.</b> {items}</div>'
