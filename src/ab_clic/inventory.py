"""Prepare CLIC's Brightway JSON against the current project and write it."""

from copy import deepcopy
from dataclasses import dataclass

import bw2data as bd
from bw2io.importers.base_lci import LCIImporter


@dataclass
class PreparedInventory:
    project: str
    technosphere: str
    biosphere: str
    importer: LCIImporter
    warnings: list[dict]

    @property
    def database(self) -> str:
        return self.importer.db_name


def _check_project(project: str, name: str, technosphere: str, biosphere: str) -> None:
    if bd.projects.current != project:
        raise ValueError(
            "The active Brightway project changed. Prepare the import again."
        )
    if name in bd.databases:
        raise ValueError(
            f"A database named {name!r} already exists. Choose another name."
        )
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
) -> PreparedInventory:
    if (package.get("schema"), package.get("schema_version")) != (
        "clic.brightway-json",
        "1.2",
    ):
        raise ValueError("This plugin expects CLIC Brightway JSON schema 1.2.")

    name = database or package["package"]["suggested_database_name"]
    _check_project(project, name, technosphere, biosphere)
    importer = LCIImporter(name)
    importer.data = deepcopy(package["activities"])
    codes = {activity["code"] for activity in importer.data}
    if not codes or len(codes) != len(importer.data):
        raise ValueError(
            "CLIC package has no activities or has duplicate activity codes."
        )

    for activity in importer.data:
        activity["database"] = name
        for exchange in activity["exchanges"]:
            link = exchange.get("input")
            if link is None:
                exchange.pop("input", None)
                continue
            if link["database"] != "__clic__" or link["code"] not in codes:
                raise ValueError(f"Invalid internal CLIC link in {activity['name']!r}.")
            exchange["input"] = (name, link["code"])

    importer.match_database(
        technosphere,
        fields=["name", "reference product", "location", "unit"],
        edge_kinds=["technosphere"],
    )
    importer.match_database(
        biosphere, fields=["name", "categories", "unit"], edge_kinds=["biosphere"]
    )

    unlinked = [
        f"{activity['name']} → {exchange.get('name') or exchange['type']}"
        for activity in importer.data
        for exchange in activity["exchanges"]
        if not exchange.get("input")
    ]
    if unlinked:
        examples = "\n".join(unlinked[:8])
        raise ValueError(
            f"{len(unlinked)} exchanges could not be linked.\n\n{examples}"
        )

    warnings = (package.get("conversion") or {}).get("warnings", [])
    return PreparedInventory(project, technosphere, biosphere, importer, warnings)


def write_inventory(prepared: PreparedInventory) -> None:
    name = prepared.database
    _check_project(prepared.project, name, prepared.technosphere, prepared.biosphere)
    # LCIImporter.write_database does not forward signal=True to the backend.
    database = bd.Database(name)
    data = {(name, activity["code"]): activity for activity in prepared.importer.data}
    try:
        database.write(data, signal=True)
    except Exception:
        if name in bd.databases:
            del bd.databases[name]
        raise
