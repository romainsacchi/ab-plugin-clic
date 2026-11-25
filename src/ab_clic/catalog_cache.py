"""Keep recently read public metadata available across catalog and import views."""

from collections import OrderedDict
from time import monotonic

MAX_RECORDS = 2048
MAX_AGE_SECONDS = 300


class CatalogCache:
    def __init__(self):
        self._records: OrderedDict[tuple[str, str], tuple[float, dict]] = OrderedDict()

    def remember(self, record: dict, slug: str | None = None) -> None:
        slug = slug or record.get("dataset_slug")
        version = record.get("semantic_version")
        if not slug or not version:
            return
        key = (slug, version)
        self._records[key] = (monotonic(), record)
        self._records.move_to_end(key)
        if len(self._records) > MAX_RECORDS:
            self._records.popitem(last=False)

    def get(self, key: tuple[str, str]) -> dict | None:
        if key not in self._records:
            return None
        saved_at, record = self._records[key]
        if monotonic() - saved_at >= MAX_AGE_SECONDS:
            del self._records[key]
            return None
        self._records.move_to_end(key)
        return record
