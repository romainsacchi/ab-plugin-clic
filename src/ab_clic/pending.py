"""Project-local CLIC job handles and exact import choices."""

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


@dataclass(frozen=True)
class ImportPlan:
    versions: list[dict]
    target: dict[str, str]
    technosphere: str
    biosphere: str
    database: str

    @property
    def version_ids(self) -> tuple[int, ...]:
        return tuple(sorted(version["id"] for version in self.versions))

    def same_export(self, other: "ImportPlan") -> bool:
        return self.version_ids == other.version_ids and self.target == other.target


@dataclass(frozen=True)
class PendingExport:
    plan: ImportPlan
    status_url: str


def pending_exports(path: Path) -> list[PendingExport]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return [
        PendingExport(ImportPlan(**entry["plan"]), entry["status_url"])
        for entry in payload
    ]


def save_pending(path: Path, export: PendingExport) -> None:
    entries = [
        entry
        for entry in pending_exports(path)
        if not entry.plan.same_export(export.plan)
    ]
    _write_pending(path, [*entries, export])


def remove_pending(path: Path, plan: ImportPlan) -> None:
    entries = pending_exports(path)
    remaining = [entry for entry in entries if not entry.plan.same_export(plan)]
    if len(entries) != len(remaining):
        _write_pending(path, remaining)


def _write_pending(path: Path, entries: list[PendingExport]) -> None:
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        temporary = Path(stream.name)
        try:
            json.dump([asdict(entry) for entry in entries], stream, ensure_ascii=False)
            stream.close()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
