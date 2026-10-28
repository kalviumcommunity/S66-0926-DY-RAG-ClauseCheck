import re
import time

import streamlit as st

from components.api_client import ApiClient, ApiUnavailable

DOC_TYPES = ["amendment", "contract", "certificate", "price_schedule"]
UPLOAD_TYPES = ["pdf", "html", "htm", "docx", "txt"]


def slugify(name: str) -> str:
    """A contract name as an ID: `Q3 Supply Deal (2025)` becomes `q3-supply-deal-2025`."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@st.cache_data(ttl=60, show_spinner=False)
def _load_contracts(base_url: str) -> list[dict]:
    return ApiClient(base_url).suppliers()


def list_contracts(api: ApiClient) -> list[dict]:
    """Every contract, sorted by name; empty if the backend cannot be reached."""
    try:
        contracts = _load_contracts(api.base_url)
    except Exception:
        return []
    return sorted(contracts, key=lambda c: (c.get("display_name") or c["supplier_id"]).lower())


def refresh_contracts() -> None:
    """Call after an upload so the new contract shows up in the list straight away."""
    _load_contracts.clear()


def contract_documents(api: ApiClient, contract_id: str) -> list[dict]:
    try:
        return api.documents(contract_id)
    except Exception:
        return []


def describe_documents(docs: list[dict]) -> list[str]:
    """One line per document: title, type, date and which document an amendment changes."""
    titles = {d["doc_id"]: d.get("title") or d["doc_id"] for d in docs}
    lines = []
    for d in sorted(docs, key=lambda d: (d.get("effective_date") or "", d.get("title") or "")):
        parts = [f"**{d.get('title') or d['doc_id']}**", (d.get("doc_type") or "document")]
        if d.get("effective_date"):
            parts.append(f"effective {d['effective_date']}")
        if d.get("parent_doc_id"):
            parts.append(f"amends {titles.get(d['parent_doc_id'], d['parent_doc_id'])}")
        elif d.get("doc_type") == "amendment":
            parts.append("not linked to an agreement")
        lines.append(" · ".join(parts))
    return lines


def unlinked_amendments(docs: list[dict]) -> list[str]:
    """Titles of amendments that were not linked to the agreement they change."""
    return [
        d.get("title") or d["doc_id"]
        for d in docs
        if d.get("doc_type") == "amendment" and not d.get("parent_doc_id")
    ]


def wait_for_job(api: ApiClient, job_id: str, timeout: float = 180.0, sleep=time.sleep) -> dict:
    """Poll an upload job until it is done or failed; status `timeout` if it takes too long."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = api.job(job_id)
        if job.get("status") in ("done", "failed"):
            return job
        sleep(1.0)
    return {"status": "timeout"}


def upload_and_wait(
    api: ApiClient,
    filename: str,
    content: bytes,
    contract_id: str,
    doc_type: str,
    display_name: str | None = None,
    sleep=time.sleep,
) -> dict:
    """Upload one file and wait until it is indexed.

    Returns `{"status", "message", "doc_id"}`; status is `done`, `failed`, `timeout`,
    `duplicate`, `rejected` (the server refused the file) or `error` (the server was not reachable).
    """
    try:
        res = api.upload(filename, content, contract_id, doc_type, display_name)
    except ValueError as exc:
        return {"status": "rejected", "message": str(exc), "doc_id": None}
    except ApiUnavailable:
        return {"status": "error", "message": "The backend is not reachable.", "doc_id": None}
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Upload failed ({type(exc).__name__}).",
            "doc_id": None,
        }
    if res.get("duplicate"):
        return {
            "status": "duplicate",
            "message": "This exact file is already indexed.",
            "doc_id": res.get("doc_id"),
        }
    try:
        job = wait_for_job(api, res["job_id"], sleep=sleep)
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Upload failed ({type(exc).__name__}).",
            "doc_id": None,
        }
    return {"status": job["status"], "message": job.get("error") or "", "doc_id": job.get("doc_id")}
