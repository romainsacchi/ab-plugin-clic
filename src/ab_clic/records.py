"""Record completed CLIC imports in Brightway database metadata."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import bw2data as bd

if TYPE_CHECKING:
    from .inventory import PreparedInventory

IMPORT_METADATA = "clic_import"


def import_record(prepared: PreparedInventory) -> dict:
    manifest = prepared.manifest
    helpers = set(manifest.get("generated_helper_codes") or ())
    roots = set(manifest.get("focal_activity_codes") or ())
    if not roots and (root := manifest.get("focal_activity_code")):
        roots.add(root)
    published = [
        activity
        for activity in prepared.importer.data
        if activity["code"] not in helpers
    ]
    ids = manifest.get("included_version_ids") or []
    # CLIC serializes its published activities in included_version_ids order, then appends helpers.
    ids_by_code = (
        dict(zip((activity["code"] for activity in published), ids, strict=True))
        if len(ids) == len(published)
        else {}
    )
    members = []
    for activity in prepared.importer.data:
        code = activity["code"]
        detail = activity.get("provenance") or {}
        catalog = detail.get("clic_catalog") or {}
        version_id = catalog.get("id") or ids_by_code.get(code)
        source_url = catalog.get("public_url") or (
            f"https://clic.psi.ch/api/versions/{version_id}/" if version_id else None
        )
        members.append(
            {
                "code": code,
                "name": activity["name"],
                "role": (
                    "helper"
                    if code in helpers
                    else "selected"
                    if code in roots
                    else "supplier"
                ),
                "version_id": version_id,
                "dataset_slug": detail.get("dataset_slug"),
                "semantic_version": detail.get("semantic_version"),
                "source_url": source_url,
                "license": catalog.get("selected_license"),
            }
        )
    return {
        "schema_version": 1,
        "completed_at": None,
        "project": prepared.project,
        "destination_database": prepared.database,
        "root_version_ids": manifest.get("root_version_ids") or [],
        "included_version_ids": ids,
        "activities": members,
        "target": prepared.target,
        "technosphere_database": prepared.technosphere,
        "biosphere_database": prepared.biosphere,
        "conversion_fingerprint": manifest.get("conversion_fingerprint"),
        "conversion_warnings": prepared.warnings,
    }


def complete_import(database: str) -> None:
    bd.databases[database][IMPORT_METADATA]["completed_at"] = datetime.now(
        UTC
    ).isoformat()
    bd.databases.flush()


def imported_versions() -> dict[int, list[str]]:
    """Resolve exact CLIC version IDs against completed databases in this project."""
    by_version = defaultdict(list)
    for name in sorted(bd.databases):
        metadata = bd.databases[name]
        record = metadata.get(IMPORT_METADATA) or {}
        if (
            record.get("schema_version") != 1
            or not record.get("completed_at")
            or not metadata.get("number")
        ):
            continue
        # Only flag activities still present after local edits to the foreground database.
        database = bd.Database(name)
        seen = set()
        for activity in record.get("activities") or []:
            version_id, code = activity.get("version_id"), activity.get("code")
            if (
                version_id
                and code
                and version_id not in seen
                and (name, code) in database
            ):
                by_version[version_id].append(name)
                seen.add(version_id)
    return dict(by_version)
