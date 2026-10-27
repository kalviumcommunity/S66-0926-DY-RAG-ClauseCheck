import streamlit as st


@st.cache_data(ttl=300)
def _suppliers_cached(api):
    return api.suppliers()


def render_sidebar(api):
    st.sidebar.title("ClauseCheck")
    try:
        suppliers = _suppliers_cached(api)
    except Exception:
        suppliers = []
    options = [None] + [s["supplier_id"] for s in suppliers]
    labels = ["All suppliers"] + [s.get("display_name", s["supplier_id"]) for s in suppliers]
    idx = st.sidebar.selectbox("Supplier", range(len(options)), format_func=lambda i: labels[i])
    supplier_filter = options[idx]

    if st.sidebar.button("New conversation"):
        st.session_state["messages"] = []
        st.session_state["session_id"] = api.new_session()

    # upload form
    with st.sidebar.form("upload"):
        f = st.file_uploader("File")
        supplier_id = st.text_input("Supplier ID")
        doc_type = st.selectbox("Doc type", ["contract", "certificate", "price_schedule"])
        submitted = st.form_submit_button("Upload")
    if submitted and f is not None:
        try:
            res = api.upload(f.name, f.read(), supplier_id, doc_type)
            if res.get("duplicate"):
                st.sidebar.warning("Duplicate document")
            else:
                job_id = res["job_id"]
                st.session_state["upload_job_id"] = job_id
                st.sidebar.info(f"Queued {job_id}")
        except ValueError as exc:
            st.sidebar.error(str(exc))
        except Exception as exc:
            st.sidebar.error(str(exc))

    job_id = st.session_state.get("upload_job_id")
    if job_id:
        try:
            job = api.job(job_id)
            st.sidebar.write(job.get("status"))
            if job.get("status") in ("done", "failed"):
                st.session_state["upload_job_id"] = None
        except Exception:
            pass

    # index status
    try:
        h = api.health()
        st.sidebar.write(
            f"docs={h.get('documents')} chunks={h.get('chunks')} suppliers={h.get('suppliers')}"
        )
        st.sidebar.write(h.get("status"))
    except Exception:
        st.sidebar.error("backend down")

    return supplier_filter
