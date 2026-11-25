"""Read published CLIC metadata and export selected versions together."""

import time
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

import requests

CLIC_URL = "https://clic.psi.ch"
PAGE_SIZE = 25
MAX_EXPORT_VERSIONS = 100


class ClicError(RuntimeError):
    """A CLIC operation could not be completed."""


class ClicClient:
    def __init__(self, session: requests.Session):
        self.session = session

    def search_versions(self, name: str, page: int) -> dict:
        return self._request(
            "GET",
            "/api/versions/",
            params={"name": name, "page": page, "page_size": PAGE_SIZE},
        )

    def export(self, version_ids: Iterable[int], target: dict, token: str) -> dict:
        ids = sorted(set(version_ids))
        if not 1 <= len(ids) <= MAX_EXPORT_VERSIONS:
            raise ClicError(
                f"Select 1 to {MAX_EXPORT_VERSIONS} CLIC versions to export."
            )
        path = f"/api/versions/{ids[0]}/brightway-json-jobs/"
        payload = {**target, "version_ids": ids[1:]} if len(ids) > 1 else target
        job = self._request("POST", path, token=token, json=payload)
        deadline = time.monotonic() + 180
        while job["status"] in {"queued", "processing"}:
            if time.monotonic() >= deadline:
                raise ClicError(
                    "CLIC is still preparing the export. Try again later to reuse the job."
                )
            time.sleep(2)
            job = self._request("GET", job["status_url"], token=token)

        if job["status"] != "succeeded":
            error = job.get("error") or {}
            detail = error.get("detail") or error.get("message") or job["status"]
            raise ClicError(f"CLIC could not prepare this export. {detail}")

        package = self._request("GET", job["result_url"], token=token)
        returned_ids = package.get("package", {}).get("root_version_ids", [])
        if sorted(returned_ids) != ids:
            raise ClicError(
                "CLIC returned a package for a different selection of versions."
            )
        return package

    def _request(self, method: str, path: str, *, token: str = "", **kwargs) -> dict:
        url = urljoin(CLIC_URL, path)
        destination = urlsplit(url)
        if (destination.scheme, destination.netloc) != ("https", "clic.psi.ch"):
            raise ClicError("CLIC returned a URL on another origin.")

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                timeout=(5, 30),
                allow_redirects=False,
                **kwargs,
            )
        except requests.RequestException:
            raise ClicError(
                "Could not reach CLIC. Check the connection and try again."
            ) from None

        if response.status_code in {401, 403}:
            raise ClicError(
                "Check that your CLIC token is valid and has inventory download access."
            )
        if not response.ok or 300 <= response.status_code < 400:
            detail = ""
            if response.status_code == 422:
                try:
                    detail = response.json().get("detail", "")
                except requests.exceptions.JSONDecodeError:
                    pass
            raise ClicError(
                f"CLIC returned HTTP {response.status_code}. {detail}".strip()
            )
        try:
            return response.json()
        except requests.exceptions.JSONDecodeError:
            raise ClicError("CLIC returned an invalid JSON response.") from None
