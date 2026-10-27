import streamlit as st


def render_sources(citations, sources, api):
    src_map = {s.get("chunk_id"): s for s in (sources or [])}
    for c in citations or []:
        chunk_id = c.get("chunk_id")
        marker = c.get("marker", "")
        src = src_map.get(chunk_id, {})
        doc = src.get("doc_id", "")
        page = src.get("page", "")
        clause = src.get("clause_no", "")
        title = f"[{marker}] {doc} · page {page} · clause {clause}"
        with st.expander(title):
            if st.button("View full clause", key=f"view-{chunk_id}-{marker}"):
                try:
                    full = api.chunk(chunk_id)
                    st.text(full.get("text", ""))
                except Exception as exc:
                    st.error(str(exc))
