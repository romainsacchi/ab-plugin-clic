"""Read published CLIC metadata and export selected versions together."""

import logging
import time
from collections.abc import Iterable
from urllib.parse import quote, urljoin, urlsplit

import requests

from .metadata import inventory_comment
from .progress import PreparationStep, ProgressCallback, ignore_progress

CLIC_URL = "https://clic.psi.ch"
PAGE_SIZE = 25
MAX_EXPORT_VERSIONS = 100
YEAR_FIELDS = {"publication_year", "inventory_reference_year"}
logger = logging.getLogger(__name__)


class ClicError(RuntimeError):
    """A CLIC operation could not be completed."""


def has_noncommercial_license(version: dict) -> bool:
    return (version.get("selected_license") or "").startswith("CC-BY-NC-")


class ClicClient:
    def __init__(self, session: requests.Session):
        self.session = session

    def search_versions(
        self,
        query: str,
        page: int,
        *,
        field: str = "name",
        exclude_noncommercial: bool = False,
        direction: int = 1,
    ) -> dict:
        params = {"page_size": PAGE_SIZE}
        if query and field in YEAR_FIELDS:
            query = query.lstrip("0")
            if len(query) > 4 or not query.isascii() or not query.isdecimal():
                raise ClicError("Enter a year between 1 and 9999.")
            params[f"{field}_min"] = params[f"{field}_max"] = query
        elif query:
            params[field] = query

        while True:
            result = self._request(
                "GET", "/api/versions/", params={**params, "page": page}
            )
            if not exclude_noncommercial:
                return result
            result["results"] = [
                version
                for version in result["results"]
                if not has_noncommercial_license(version)
            ]
            if result["results"] or not result["next" if direction > 0 else "previous"]:
                return result
            page = result["page"] + direction

    def export(
        self,
        version_ids: Iterable[int],
        target: dict,
        token: str,
        *,
        on_progress: ProgressCallback = ignore_progress,
    ) -> dict:
        ids = sorted(set(version_ids))
        if not 1 <= len(ids) <= MAX_EXPORT_VERSIONS:
            raise ClicError(
                f"Select 1 to {MAX_EXPORT_VERSIONS} CLIC versions to export."
            )
        path = f"/api/versions/{ids[0]}/brightway-json-jobs/"
        payload = {**target, "version_ids": ids[1:]} if len(ids) > 1 else target
        on_progress(
            PreparationStep.REQUEST_EXPORT, "Requesting a Brightway export from CLIC…"
        )
        job = self._request("POST", path, token=token, json=payload)
        deadline = time.monotonic() + 180
        wait_messages = {
            "queued": "CLIC has queued the export. Waiting for it to start…",
            "processing": "CLIC is preparing the Brightway package…",
        }
        previous_status = None
        while job["status"] in wait_messages:
            status = job["status"]
            if status != previous_status:
                on_progress(PreparationStep.WAIT_FOR_EXPORT, wait_messages[status])
                previous_status = status
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

        on_progress(
            PreparationStep.DOWNLOAD_PACKAGE,
            "Downloading the Brightway package from CLIC…",
        )
        package = self._request("GET", job["result_url"], token=token)
        returned_ids = package.get("package", {}).get("root_version_ids", [])
        if sorted(returned_ids) != ids:
            raise ClicError(
                "CLIC returned a package for a different selection of versions."
            )
        return package

    def add_inventory_metadata(
        self,
        package: dict,
        selected_versions: Iterable[dict],
        *,
        on_progress: ProgressCallback = ignore_progress,
    ) -> None:
        """Add exact-version descriptions and metadata to Brightway activity comments."""
        on_progress(PreparationStep.READ_METADATA, "Reading published CLIC metadata…")
        records = {
            (version["dataset_slug"], version["semantic_version"]): version
            for version in selected_versions
            if "dataset_slug" in version
        }
        activities = []
        by_slug = {}
        for activity in package.get("activities", []):
            provenance = activity.get("provenance") or {}
            slug = provenance.get("dataset_slug")
            version = provenance.get("semantic_version")
            if not slug or not version:
                continue
            identity = (slug, version)
            activities.append((identity, activity))
            if identity not in records:
                by_slug.setdefault(slug, set()).add(version)

        for number, (slug, versions) in enumerate(by_slug.items(), start=1):
            on_progress(
                PreparationStep.READ_METADATA,
                f"Reading published CLIC metadata ({number} of {len(by_slug)} catalog records)…",
            )
            try:
                dataset = self._request("GET", f"/api/datasets/{quote(slug, safe='')}/")
            except ClicError as exc:
                logger.warning("Could not read CLIC metadata for %s: %s", slug, exc)
                continue
            records.update(
                {
                    (slug, version["semantic_version"]): version
                    for version in dataset.get("published_versions", [])
                    if version["semantic_version"] in versions
                }
            )

        for identity, activity in activities:
            if identity in records:
                comment = inventory_comment(
                    records[identity], activity.get("comment") or ""
                )
                if comment:
                    activity["comment"] = comment

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
