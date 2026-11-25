"""Prepare CLIC's Brightway JSON against the current project and write it."""

from copy import deepcopy
from dataclasses import dataclass

import bw2data as bd
from bw2io.importers.base_lci import LCIImporter

from .linking import LinkIssue, describe_exchange, match_external_links
from .progress import PreparationStep, ProgressCallback, ignore_progress
from .records import IMPORT_METADATA, complete_import, import_record


@dataclass
class PreparedInventory:
    project: str
    technosphere: str
    biosphere: str
    importer: LCIImporter
    warnings: list[dict]
    issues: list[LinkIssue]
    manifest: dict
    target: dict

    @property
    def database(self) -> str:
        return self.importer.db_name


def check_project(project: str, name: str, technosphere: str, biosphere: str) -> None:
    if bd.projects.current != project:
        raise ValueError(
            "The active Brightway project changed. Prepare the import again."
        )
    if name in bd.databases:
        raise ValueError(
            f"A database named {name!r} already exists. Choose another name."
        )
    if technosphere == biosphere:
        raise ValueError("Choose separate technosphere and biosphere databases.")
    for name in (technosphere, biosphere):
        if name not in bd.databases:
            raise ValueError(f"Database {name!r} is missing from project {project!r}.")


def prepare_inventory(
    package: dict,
    *,
    project: str,
    technosphere: str,
    biosphere: str,
    database: str = "",
    expected_target: dict | None = None,
    on_progress: ProgressCallback = ignore_progress,
) -> PreparedInventory:
    on_progress(
        PreparationStep.CHECK_PACKAGE,
        "Checking the package and linking its activities…",
    )
    if (package.get("schema"), package.get("schema_version")) != (
        "clic.brightway-json",
        "1.2",
    ):
        raise ValueError("This plugin expects CLIC Brightway JSON schema 1.2.")

    manifest = package["package"]
    target = package.get("resolved_target") or {}
    if expected_target is not None and any(
        target.get(key) != value for key, value in expected_target.items()
    ):
        raise ValueError(
            "CLIC returned an export for a different background. Check the target and prepare it again."
        )
    name = database or manifest["suggested_database_name"]
    check_project(project, name, technosphere, biosphere)
    importer = LCIImporter(name)
    importer.data = deepcopy(package["activities"])
    codes = {activity["code"] for activity in importer.data}
    if not codes or len(codes) != len(importer.data):
        raise ValueError(
            "CLIC package has no activities or has duplicate activity codes."
        )

    issues = []
    for activity in importer.data:
        activity["database"] = name
        for exchange in activity["exchanges"]:
            link = exchange.get("input")
            if link is None:
                exchange.pop("input", None)
                continue
            if link["database"] != "__clic__" or link["code"] not in codes:
                issues.append(
                    LinkIssue(
                        activity["name"],
                        describe_exchange(exchange),
                        name,
                        f"Invalid internal target {link['code']}",
                        "Report the affected version and exchange to CLIC.",
                    )
                )
                continue
            exchange["input"] = (name, link["code"])

    on_progress(
        PreparationStep.MATCH_TECHNOSPHERE,
        f"Matching technosphere exchanges to {technosphere}…",
    )
    issues.extend(match_external_links(importer.data, "technosphere", technosphere))
    on_progress(
        PreparationStep.MATCH_BIOSPHERE, f"Matching biosphere exchanges to {biosphere}…"
    )
    issues.extend(match_external_links(importer.data, "biosphere", biosphere))

    on_progress(PreparationStep.CHECK_LINKS, "Checking for unresolved exchanges…")
    issues.extend(
        LinkIssue(
            activity["name"],
            describe_exchange(exchange),
            name,
            "No portable input link",
            "Report this exchange and its CLIC version to CLIC.",
        )
        for activity in importer.data
        for exchange in activity["exchanges"]
        if not exchange.get("input")
        and exchange.get("type") not in {"technosphere", "biosphere"}
    )

    warnings = (package.get("conversion") or {}).get("warnings", [])
    return PreparedInventory(
        project, technosphere, biosphere, importer, warnings, issues, manifest, target
    )


def write_inventory(prepared: PreparedInventory) -> None:
    if prepared.issues:
        raise ValueError("Resolve all exchange links before importing.")
    name = prepared.database
    check_project(prepared.project, name, prepared.technosphere, prepared.biosphere)
    # LCIImporter.write_database does not forward signal=True to the backend.
    database = bd.Database(name)
    data = {(name, activity["code"]): activity for activity in prepared.importer.data}
    try:
        database.register(
            write_empty=False, **{IMPORT_METADATA: import_record(prepared)}
        )
        database.write(data, signal=True)
        complete_import(name)
    except Exception:
        if name in bd.databases:
            del bd.databases[name]
        raise
