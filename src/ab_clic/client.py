"""Read published CLIC metadata and export selected versions together."""

import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from threading import Event, Lock, local
from urllib.parse import quote, unquote, urljoin, urlsplit

import requests

from .catalog_cache import CatalogCache
from .metadata import inventory_comment
from .progress import PreparationStep, ProgressCallback, ignore_progress

CLIC_URL = "https://clic.psi.ch"
PAGE_SIZE = 25
MAX_EXPORT_VERSIONS = 100
METADATA_WORKERS = 6
YEAR_FIELDS = {"publication_year", "inventory_reference_year"}
DATASET_LINK = re.compile(
    r"/(?:api/)?datasets/([a-zA-Z0-9_-]+)(?:/versions/(\d+(?:\.\d+\.\d+)?))?/?"
)
VERSION_API_LINK = re.compile(r"/api/versions/([1-9]\d*)/?")
logger = logging.getLogger(__name__)


class ClicError(RuntimeError):
    """A CLIC operation could not be completed."""


class ExportDeferred(Exception):
    """The user stopped waiting for a saved CLIC export job."""


class ExportRejected(ClicError):
    """The server reported that this export job failed."""


def has_noncommercial_license(version: dict) -> bool:
    return (version.get("selected_license") or "").startswith("CC-BY-NC-")


def _matches_columns(version: dict, filters: Mapping[str, tuple[str, bool]]) -> bool:
    for field, (term, exclude) in filters.items():
        value = str(version.get(field) or "").casefold()
        matches = term in value if field == "name" else term == value
        if matches == exclude:
            return False
    return True


class ClicClient:
    def __init__(
        self, session: requests.Session, catalog_cache: CatalogCache | None = None
    ):
        self.session = session
        self.catalog_cache = (
            catalog_cache if catalog_cache is not None else CatalogCache()
        )

    def dataset_from_link(self, link: str) -> dict:
        try:
            url = urlsplit(link.strip())
        except ValueError:
            raise ClicError("Paste a CLIC dataset or published-version link.") from None
        if (url.scheme, url.netloc) != ("https", "clic.psi.ch"):
            raise ClicError("Paste a link from https://clic.psi.ch.")
        path = unquote(url.path)
        if version_api := VERSION_API_LINK.fullmatch(path):
            record = self._request("GET", f"/api/versions/{version_api[1]}/")
            self.catalog_cache.remember(record)
            return record
        if not (dataset_link := DATASET_LINK.fullmatch(path)):
            raise ClicError("Paste a CLIC dataset or published-version link.")
        slug, revision = dataset_link.groups()
        if revision and revision.isascii() and revision.isdecimal():
            version = self._request("GET", f"/api/versions/{revision}/")
            if version.get("dataset_slug") != slug:
                raise ClicError("The CLIC version is not part of this dataset.")
            self.catalog_cache.remember(version)
            return version
        dataset = self._request("GET", f"/api/datasets/{slug}/")
        if not revision:
            latest = dataset["latest_published_version"]
            self.catalog_cache.remember(latest, slug)
            return latest
        for version in dataset.get("published_versions", []):
            if version["semantic_version"] == revision:
                self.catalog_cache.remember(version, slug)
                return version
        raise ClicError(f"Published version {revision} is unavailable in CLIC.")

    def search_datasets(
        self,
        query: str,
        page: int,
        *,
        field: str = "name",
        exclude_noncommercial: bool = False,
        column_filters: Mapping[str, tuple[str, bool]] | None = None,
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
        filters = {
            field: (term.casefold(), exclude)
            for field, (term, exclude) in (column_filters or {}).items()
        }

        while True:
            result = self._request(
                "GET", "/api/datasets/", params={**params, "page": page}
            )
            latest_versions = [
                dataset["latest_published_version"] for dataset in result["results"]
            ]
            for version in latest_versions:
                self.catalog_cache.remember(version)
            if not exclude_noncommercial and not filters:
                return {**result, "results": latest_versions}
            matches = [
                version
                for version in latest_versions
                if (not exclude_noncommercial or not has_noncommercial_license(version))
                and _matches_columns(version, filters)
            ]
            if matches or not result["next" if direction > 0 else "previous"]:
                return {**result, "results": matches}
            page = result["page"] + direction

    def export(
        self,
        version_ids: Iterable[int],
        target: dict,
        token: str,
        *,
        on_progress: ProgressCallback = ignore_progress,
        status_url: str = "",
        on_job: Callable[[str], None] | None = None,
        stop: Event | None = None,
    ) -> dict:
        ids = sorted(set(version_ids))
        if not 1 <= len(ids) <= MAX_EXPORT_VERSIONS:
            raise ClicError(
                f"Select 1 to {MAX_EXPORT_VERSIONS} CLIC versions to export."
            )
        if status_url:
            on_progress(
                PreparationStep.WAIT_FOR_EXPORT, "Checking your saved CLIC export…"
            )
            job = self._request("GET", status_url, token=token)
        else:
            path = f"/api/versions/{ids[0]}/brightway-json-jobs/"
            payload = {**target, "version_ids": ids[1:]} if len(ids) > 1 else target
            on_progress(
                PreparationStep.REQUEST_EXPORT,
                "Requesting a Brightway export from CLIC…",
            )
            job = self._request("POST", path, token=token, json=payload)
            if on_job is not None:
                on_job(job["status_url"])
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
                    "CLIC is still preparing the export. Resume it from Pending exports."
                )
            if stop is None:
                time.sleep(2)
            elif stop.wait(2):
                raise ExportDeferred
            status_url = job.get("status_url") or status_url
            job = self._request("GET", status_url, token=token)

        if stop is not None and stop.is_set():
            raise ExportDeferred
        if job["status"] != "succeeded":
            error = job.get("error") or {}
            detail = error.get("detail") or error.get("message") or job["status"]
            raise ExportRejected(f"CLIC could not prepare this export. {detail}")

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
                cached = self.catalog_cache.get(identity)
                if cached is None:
                    by_slug.setdefault(slug, set()).add(version)
                else:
                    records[identity] = cached

        if by_slug:
            on_progress(
                PreparationStep.READ_METADATA,
                f"Reading published CLIC metadata (0 of {len(by_slug)} datasets checked)…",
            )
        for checked, (slug, versions) in enumerate(
            self._read_catalog_metadata(by_slug), start=1
        ):
            for record in versions:
                self.catalog_cache.remember(record, slug)
                records[slug, record["semantic_version"]] = record
            on_progress(
                PreparationStep.READ_METADATA,
                f"Reading published CLIC metadata ({checked} of {len(by_slug)} datasets checked)…",
            )

        for identity, activity in activities:
            if identity in records:
                record = records[identity]
                activity["provenance"]["clic_catalog"] = {
                    key: record[key]
                    for key in (
                        "id",
                        "public_url",
                        "selected_license",
                        "selected_license_label",
                    )
                    if record.get(key) is not None
                }
                comment = inventory_comment(record, activity.get("comment") or "")
                if comment:
                    activity["comment"] = comment

    def _read_catalog_metadata(self, by_slug: dict[str, set[str]]):
        if len(by_slug) <= 1:
            for slug, revisions in by_slug.items():
                yield slug, self._read_dataset_versions(slug, revisions)
            return

        worker_state = local()
        lock = Lock()
        with ExitStack() as sessions:

            def read(slug, revisions):
                # Requests sessions own mutable state. Each worker reuses its own connection.
                if not hasattr(worker_state, "client"):
                    with lock:
                        session = sessions.enter_context(requests.Session())
                    worker_state.client = ClicClient(session)
                return slug, worker_state.client._read_dataset_versions(slug, revisions)

            with ThreadPoolExecutor(max_workers=METADATA_WORKERS) as workers:
                futures = [
                    workers.submit(read, slug, revisions)
                    for slug, revisions in by_slug.items()
                ]
                for future in as_completed(futures):
                    yield future.result()

    def _read_dataset_versions(self, slug: str, revisions: set[str]) -> list[dict]:
        try:
            dataset = self._request("GET", f"/api/datasets/{quote(slug, safe='')}/")
        except ClicError as exc:
            logger.warning("Could not read CLIC metadata for %s: %s", slug, exc)
            return []
        return [
            record
            for record in dataset.get("published_versions", [])
            if record.get("semantic_version") in revisions
        ]

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
