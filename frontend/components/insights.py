import streamlit as st

KPI_LABELS = {
    "questions_asked": "Questions asked",
    "answer_rate": "Answer rate",
    "median_time_to_checked_answer_ms": "Time to checked answer",
    "median_ttft_ms": "Time to first token",
    "citation_accuracy": "Citation accuracy",
}


def format_kpi(key: str, value) -> str:
    if value is None:
        return "—"
    if key in ("answer_rate", "citation_accuracy"):
        return f"{round(value * 100)}%"
    if key.endswith("_ms"):
        if value < 1000:
            return f"{int(value)} ms"
        return f"{value / 1000:.1f} s"
    if isinstance(value, float):
        return f"{value:,.0f}"
    return f"{value:,}"


def render_insights(api):
    try:
        kpis = api.kpis()
    except Exception:
        kpis = {}
    cols = st.columns(5)
    for i, key in enumerate(KPI_LABELS):
        cols[i].metric(KPI_LABELS[key], format_kpi(key, kpis.get(key)))

    try:
        charts = api.charts()
    except Exception:
        charts = {}
    try:
        tables = api.tables()
    except Exception:
        tables = {}

    # charts (simplified)
    st.write("Outcomes by day")
    st.write(charts.get("outcomes_by_day", []))
    st.write("Latency by day")
    st.write(charts.get("latency_by_day", []))
    st.write("Questions by topic")
    st.write(charts.get("questions_by_topic", []))
    st.write("Documents by source")
    st.write(charts.get("documents_by_source", []))

    # tables
    st.write("Supplier activity")
    st.write(tables.get("supplier_activity", []))
    st.write("Unanswered")
    st.write(tables.get("unanswered", []))
    st.write("Evaluation")
    st.write(tables.get("evaluation", []))
    st.write("Coverage")
    st.write(tables.get("coverage", []))
