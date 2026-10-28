from typing import Any

import httpx


class ApiUnavailable(Exception):
    pass


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 15.0, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client or httpx.Client(base_url=self.base_url, timeout=timeout)

    def _request(self, method: str, path: str, **kwargs):
        try:
            r = self._client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ApiUnavailable(str(exc)) from exc
        if r.status_code >= 400:
            if r.status_code in (413, 415):
                raise ValueError(r.json().get("detail", r.text))
            r.raise_for_status()
        return r

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health").json()

    def suppliers(self) -> list[dict[str, Any]]:
        return self._request("GET", "/suppliers").json()

    def new_session(self) -> str:
        return self._request("POST", "/sessions").json()["session_id"]

    def chunk(self, chunk_id: str) -> dict[str, Any]:
        return self._request("GET", f"/chunks/{chunk_id}").json()

    def documents(self, supplier_id: str) -> list[dict[str, Any]]:
        """The documents of one contract (a contract and its amendments, certificates, ...)."""
        params = {"supplier_id": supplier_id, "limit": 200}
        return self._request("GET", "/documents", params=params).json()["items"]

    def contracts(self) -> list[dict[str, Any]]:
        """The register: each contract with its documents, latest effective date, last check."""
        return self._request("GET", "/contracts").json()

    def recent_checks(self, limit: int = 5, contract_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if contract_id:
            params["contract_id"] = contract_id
        return self._request("GET", "/checks/recent", params=params).json()

    def common_questions(self, contract_id: str, limit: int = 5) -> list[str]:
        path = f"/contracts/{contract_id}/common-questions"
        return self._request("GET", path, params={"limit": limit}).json()

    def report(self, days: str = "7", contract_id: str | None = None) -> dict[str, Any]:
        params = {"days": days, **({"contract_id": contract_id} if contract_id else {})}
        return self._request("GET", "/insights/report", params=params).json()

    def upload(
        self,
        filename: str,
        content: bytes,
        supplier_id: str,
        doc_type: str = "contract",
        display_name: str | None = None,
        effective_date: str | None = None,
        amends: str | None = None,
    ):
        files = {"file": (filename, content)}
        data = {"supplier_id": supplier_id, "doc_type": doc_type}
        if display_name:
            data["display_name"] = display_name
        if effective_date:
            data["effective_date"] = effective_date
        if amends:
            data["amends"] = amends
        r = self._request_raw("POST", "/documents", files=files, data=data)
        if r.status_code == 409:
            body = r.json()
            return {"duplicate": True, "doc_id": body.get("doc_id")}
        if r.status_code in (413, 415, 422):
            raise ValueError(r.json().get("detail", r.text))
        if r.status_code >= 400:
            r.raise_for_status()
        return r.json()

    def _request_raw(self, method: str, path: str, **kwargs):
        try:
            return self._client.request(method, path, **kwargs)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ApiUnavailable(str(exc)) from exc

    def job(self, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/documents/jobs/{job_id}").json()

    def feedback(self, query_id: str, rating: str) -> None:
        self._request("POST", "/feedback", json={"query_id": query_id, "rating": rating})

    def kpis(self) -> dict[str, Any]:
        return self._request("GET", "/insights/kpis").json()

    def charts(self) -> dict[str, Any]:
        return self._request("GET", "/insights/charts").json()

    def tables(self) -> dict[str, Any]:
        return self._request("GET", "/insights/tables").json()
