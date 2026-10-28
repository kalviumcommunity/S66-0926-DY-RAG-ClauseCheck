"""Contracts and filings: the register, a contract's documents, and filing step by step."""

import re
import time
from collections.abc import Iterator

import streamlit as st

from components.api_client import ApiClient, ApiUnavailable

DOC_TYPES = {
    "Contract": "contract",
    "Price schedule": "price_schedule",
    "Certificate": "certificate",
}
UPLOAD_TYPES = ["pdf", "docx", "html", "htm", "txt"]
MAX_UPLOAD_MB = 20  # the same limit as the backend's MAX_UPLOAD_MB and the Streamlit config


def slugify(name: str) -> str:
    """A contract name as an ID: `Q3 Supply Deal (2025)` becomes `q3-supply-deal-2025`."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@st.cache_data(ttl=30, show_spinner=False)
def _load_contracts(base_url: str) -> list[dict]:
    return ApiClient(base_url).contracts()


def list_contracts(api: ApiClient) -> list[dict]:
    """The register, most recently checked first; empty if the backend cannot be reached."""
    try:
        return _load_contracts(api.base_url)
    except Exception:
        return []


def refresh_contracts() -> None:
    """Call after a filing so the new contract shows up in the register straight away."""
    _load_contracts.clear()


def contract_documents(api: ApiClient, contract_id: str) -> list[dict]:
    try:
        return api.documents(contract_id)
    except Exception:
        return []


def too_big(filename: str, size_bytes: int) -> str | None:
    """Our own wording for a file over the limit, or None. Streamlit enforces the same limit."""
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        return (
            f"{filename} is {size_bytes / (1024 * 1024):.1f} MB. Files can be at most "
            f"{MAX_UPLOAD_MB} MB; split it, or file the sections that matter."
        )
    return None


def valid_date(text: str) -> bool:
    """An empty date is fine (it is read from the document); otherwise YYYY-MM-DD."""
    return not text.strip() or bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text.strip()))


def file_document(
    api: ApiClient,
    filename: str,
    content: bytes,
    contract_id: str,
    doc_type: str,
    *,
    display_name: str | None = None,
    effective_date: str | None = None,
    amends: str | None = None,
    poll: float = 0.5,
    timeout: float = 240.0,
    sleep=time.sleep,
) -> Iterator[tuple[str, dict]]:
    """File one document and follow it. Yields `(kind, data)` until it ends.

    Kinds: `rejected` (the server refused the file, `data["message"]`), `error` (the backend was not
    reachable), `duplicate` (`data["doc_id"]`), and `job` (the job as the API reports it, with its
    `steps`, repeated on every poll; the last one has status `done`, `failed` or `timeout`).
    """
    try:
        result = api.upload(
            filename,
            content,
            contract_id,
            doc_type,
            display_name,
            effective_date or None,
            amends or None,
        )
    except ValueError as exc:
        yield "rejected", {"message": str(exc)}
        return
    except ApiUnavailable:
        yield "error", {"message": "The backend is not reachable."}
        return
    except Exception as exc:
        yield "error", {"message": f"Filing failed ({type(exc).__name__})."}
        return
    if result.get("duplicate"):
        yield "duplicate", {"doc_id": result.get("doc_id")}
        return
    deadline = time.monotonic() + timeout
    while True:
        try:
            job = api.job(result["job_id"])
        except Exception as exc:
            yield "error", {"message": f"Filing failed ({type(exc).__name__})."}
            return
        if job.get("status") in ("done", "failed"):
            yield "job", job
            return
        if time.monotonic() > deadline:
            yield "job", {**job, "status": "timeout"}
            return
        yield "job", job
        sleep(poll)
