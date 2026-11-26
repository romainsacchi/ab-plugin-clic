"""Prepare CLIC's Brightway JSON against the current project and write it."""

import json
import pickle
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

import bw2data as bd
from bw2data.backends import ActivityDataset, ExchangeDataset, sqlite3_lci_db
from bw2data.configuration import labels
from bw2data.search import IndexManager
from bw2data.signals import on_database_write
from bw2data.utils import get_geocollection, set_correct_process_type
from bw2io.importers.base_lci import LCIImporter
from peewee import chunked

from .background import ecoinvent_profile
from .linking import LinkIssue, describe_exchange, match_external_links
from .progress import PreparationStep, ProgressCallback, ignore_progress
from .records import IMPORT_METADATA, complete_import, import_record, record_append


@dataclass(frozen=True)
class ActivityReplacement:
    code: str
    existing_name: str
    snapshot: bytes


@dataclass(frozen=True)
class AppendReview:
    added: tuple[str, ...]
    reused: tuple[str, ...]
    conflicts: tuple[str, ...]
    replacements: tuple[ActivityReplacement, ...] = ()


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
    append_review: AppendReview | None = None

    @property
    def database(self) -> str:
        return self.importer.db_name


def _allows_append(metadata: dict) -> bool:
    if "read_only" in metadata:
        return metadata["read_only"] is False
    # Earlier CLIC releases did not set a lock flag on the databases they created.
    receipt = metadata.get(IMPORT_METADATA) or {}
    return receipt.get("schema_version") == 1 and bool(receipt.get("completed_at"))


def writable_foregrounds(technosphere: str, biosphere: str) -> list[str]:
    candidates = {
        name
        for name, metadata in bd.databases.items()
        if name not in {technosphere, biosphere}
        and metadata.get("backend") == "sqlite"
        and _allows_append(metadata)
        and ecoinvent_profile(name) is None
    }
    if not candidates:
        return []
    types = ActivityDataset.select(ActivityDataset.database, ActivityDataset.type)
    types = types.where(ActivityDataset.database.in_(candidates)).distinct().tuples()
    populated, with_processes = set(), set()
    for name, node_type in types:
        populated.add(name)
        if node_type in labels.process_node_types:
            with_processes.add(name)
    return sorted((candidates - populated) | with_processes)


def check_project(
    project: str, name: str, technosphere: str, biosphere: str, *, append: bool = False
) -> None:
    if bd.projects.current != project:
        raise ValueError(
            "The active Brightway project changed. Prepare the import again."
        )
    if append:
        if not name:
            raise ValueError("Choose an existing foreground database for the import.")
        if name not in writable_foregrounds(technosphere, biosphere):
            raise ValueError(
                f"{name!r} is unavailable as a writable classic foreground database."
            )
    elif name in bd.databases:
        raise ValueError(
            f"A database named {name!r} already exists. Choose another name."
        )
    if technosphere == biosphere:
        raise ValueError("Choose separate technosphere and biosphere databases.")
    for background in (technosphere, biosphere):
        if background not in bd.databases:
            raise ValueError(
                f"Database {background!r} is missing from project {project!r}."
            )


def prepare_inventory(
    package: dict,
    *,
    project: str,
    technosphere: str,
    biosphere: str,
    database: str = "",
    append: bool = False,
    replace: bool = False,
    expected_target: dict | None = None,
    on_progress: ProgressCallback = ignore_progress,
) -> PreparedInventory:
    if replace and not append:
        raise ValueError(
            "Choose an existing foreground database to replace activities."
        )
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
    name = database if append else database or manifest["suggested_database_name"]
    check_project(project, name, technosphere, biosphere, append=append)
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
            if append:
                exchange["output"] = (name, activity["code"])
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
    issues.extend(
        match_external_links(
            importer.data,
            "technosphere",
            technosphere,
            check_legacy_foreground=not manifest.get("foreground_link_version"),
        )
    )
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
    append_review = (
        _review_append(name, importer.data, replace=replace) if append else None
    )
    return PreparedInventory(
        project,
        technosphere,
        biosphere,
        importer,
        warnings,
        issues,
        manifest,
        target,
        append_review,
    )


def _activity_signature(activity: dict, exchanges: list[dict]) -> tuple[str, list[str]]:
    # Individual Brightway saves can copy the storage ID into the data payload.
    data = {
        key: value for key, value in activity.items() if key not in {"exchanges", "id"}
    }
    return json.dumps(data, sort_keys=True), sorted(
        json.dumps(
            {key: value for key, value in exchange.items() if key != "id"},
            sort_keys=True,
        )
        for exchange in exchanges
    )


def _review_append(name: str, activities: list[dict], *, replace: bool) -> AppendReview:
    existing = {}
    for codes in chunked([activity["code"] for activity in activities], 400):
        nodes = ActivityDataset.select(
            ActivityDataset.code, ActivityDataset.id, ActivityDataset.data
        ).where((ActivityDataset.database == name) & ActivityDataset.code.in_(codes))
        for code, node_id, data in nodes.tuples():
            existing[code] = (node_id, data, [])
        edges = ExchangeDataset.select(
            ExchangeDataset.output_code, ExchangeDataset.id, ExchangeDataset.data
        ).where(
            (ExchangeDataset.output_database == name)
            & ExchangeDataset.output_code.in_(codes)
        )
        for code, exchange_id, data in edges.tuples():
            if code in existing:
                existing[code][2].append((exchange_id, data))

    added, reused, conflicts, replacements = [], [], [], []
    for activity in activities:
        code = activity["code"]
        if code not in existing:
            added.append(code)
            continue
        normalized = set_correct_process_type(activity.copy())
        node_id, existing_data, existing_edges = existing[code]
        try:
            matches = _activity_signature(
                normalized, activity["exchanges"]
            ) == _activity_signature(
                existing_data, [edge for _, edge in existing_edges]
            )
        except (TypeError, ValueError):
            matches = False
        if matches:
            reused.append(code)
        elif (
            replace
            and existing_data.get("type") in labels.process_node_types
            and normalized.get("type") in labels.process_node_types
        ):
            # Recheck the reviewed data and identities, including edits that still conflict.
            snapshot = sha256(
                pickle.dumps((node_id, existing_data, sorted(existing_edges)))
            ).digest()
            replacements.append(
                ActivityReplacement(code, existing_data.get("name") or code, snapshot)
            )
        else:
            conflicts.append(code)
    return AppendReview(
        tuple(added), tuple(reused), tuple(conflicts), tuple(replacements)
    )


def write_inventory(
    prepared: PreparedInventory, *, confirm_replacement: bool = False
) -> None:
    if prepared.issues:
        raise ValueError("Resolve all exchange links before importing.")
    if prepared.append_review is not None:
        if prepared.append_review.replacements and not confirm_replacement:
            raise ValueError("Confirm the listed replacements before importing.")
        _write_existing_inventory(prepared)
        return
    name = prepared.database
    check_project(prepared.project, name, prepared.technosphere, prepared.biosphere)
    # LCIImporter.write_database does not forward signal=True to the backend.
    database = bd.Database(name)
    data = {(name, activity["code"]): activity for activity in prepared.importer.data}
    try:
        database.register(
            write_empty=False,
            read_only=False,
            **{IMPORT_METADATA: import_record(prepared)},
        )
        database.write(data, signal=True)
        complete_import(name)
    except Exception:
        if name in bd.databases:
            del bd.databases[name]
        raise


@contextmanager
def _inventory_transaction(*, replace: bool):
    connection = sqlite3_lci_db.db
    if replace:
        # The formula index lives in a separate SQLite file. Remove stale rows in the same transaction.
        connection.execute_sql(
            "ATTACH DATABASE ? AS clic_parameters", (str(bd.parameters.db.db.database),)
        )
    try:
        with connection.atomic("IMMEDIATE"):
            yield
    finally:
        if replace:
            connection.execute_sql("DETACH DATABASE clic_parameters")


def _delete_replaced_exchanges(name: str, codes: set[str]) -> None:
    for batch in chunked(codes, 400):
        placeholders = ",".join("?" for _ in batch)
        sqlite3_lci_db.db.execute_sql(
            "DELETE FROM clic_parameters.parameterizedexchange WHERE exchange IN "
            "(SELECT id FROM main.exchangedataset WHERE output_database = ? "
            f"AND output_code IN ({placeholders}))",
            (name, *batch),
        )
        ExchangeDataset.delete().where(
            (ExchangeDataset.output_database == name)
            & ExchangeDataset.output_code.in_(batch)
        ).execute()


def _write_existing_inventory(prepared: PreparedInventory) -> None:
    review = prepared.append_review
    if review.conflicts:
        raise ValueError("Resolve all activity code conflicts before importing.")

    name = prepared.database
    replaced = {activity.code for activity in review.replacements}
    changed = set(review.added) | replaced
    data = {
        (name, activity["code"]): set_correct_process_type(deepcopy(activity))
        for activity in prepared.importer.data
        if activity["code"] in changed
    }
    index, original_metadata = None, None
    indexed_replacements = {}
    try:
        with _inventory_transaction(replace=bool(replaced)):
            check_project(
                prepared.project,
                name,
                prepared.technosphere,
                prepared.biosphere,
                append=True,
            )
            if (
                _review_append(name, prepared.importer.data, replace=bool(replaced))
                != review
            ):
                raise ValueError(
                    "The destination database changed. Prepare the import again."
                )
            database = bd.Database(name)
            metadata = bd.databases[name]
            record = import_record(prepared)
            record["completed_at"] = datetime.now(UTC).isoformat()
            if replaced:
                record["replaced_activity_codes"] = [
                    item.code for item in review.replacements
                ]
            updated = metadata.copy()
            record_append(updated, record)
            if not data and updated == metadata:
                return

            exchanges, activities = [], []
            _delete_replaced_exchanges(name, replaced)
            for activity in data.values():
                code = activity["code"]
                if code in replaced:
                    exchanges, [row] = database._efficient_write_dataset(
                        activity, exchanges, []
                    )
                    del row["id"]
                    matching = (ActivityDataset.database == name) & (
                        ActivityDataset.code == code
                    )
                    if metadata.get("searchable"):
                        indexed_replacements[code] = ActivityDataset.get(matching).data
                    ActivityDataset.update(**row).where(matching).execute()
                else:
                    exchanges, activities = database._efficient_write_dataset(
                        activity, exchanges, activities
                    )
            if activities:
                ActivityDataset.insert_many(activities).execute()
            if exchanges:
                ExchangeDataset.insert_many(exchanges).execute()
            if data:
                locations = {
                    activity["location"]
                    for activity in data.values()
                    if activity.get("location")
                }
                bd.geomapping.add(locations)
                geocollections = {
                    get_geocollection(location) for location in locations
                } - {None}
                updated.update(
                    number=len(database),
                    dirty=True,
                    modified=record["completed_at"],
                    depends=sorted(
                        set(metadata.get("depends") or ())
                        | set(database.find_dependents(data, ignore=[name]))
                    ),
                    geocollections=sorted(
                        set(metadata.get("geocollections") or ()) | geocollections
                    ),
                )
                if metadata.get("searchable"):
                    index = IndexManager(database.filename)
                    index.add_datasets(
                        [
                            activity
                            for activity in data.values()
                            if activity["code"] not in replaced
                        ]
                    )
                    for code in indexed_replacements:
                        index.update_dataset(data[name, code])
            original_metadata = metadata.copy()
            metadata.update(updated)
            bd.databases.flush()
    except Exception:
        if original_metadata is not None:
            bd.databases[name].clear()
            bd.databases[name].update(original_metadata)
            bd.databases.flush()
        if index is not None:
            for activity in data.values():
                if activity["code"] in indexed_replacements:
                    index.update_dataset(indexed_replacements[activity["code"]])
                else:
                    index.delete_dataset(activity)
        raise
    on_database_write.send(name=name)
