import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ab_clic.pending import (
    ImportPlan,
    PendingExport,
    pending_exports,
    remove_pending,
    save_pending,
)


class PendingExportsTests(unittest.TestCase):
    def test_project_local_jobs_round_trip_and_refresh_the_same_export(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.json"
            target = {
                "family": "ecoinvent",
                "version": "3.12",
                "system_model": "cutoff",
            }
            first = ImportPlan(
                [{"id": 2}, {"id": 1}], target, "ecoinvent", "flows", "import A"
            )
            revised = ImportPlan(
                [{"id": 1}, {"id": 2}], target, "ecoinvent", "flows", "import B"
            )
            other = ImportPlan([{"id": 3}], target, "ecoinvent", "flows", "import C")
            save_pending(path, PendingExport(first, "/api/jobs/a/"))
            save_pending(path, PendingExport(other, "/api/jobs/b/"))
            save_pending(path, PendingExport(revised, "/api/jobs/a/"))
            self.assertEqual(
                pending_exports(path),
                [
                    PendingExport(other, "/api/jobs/b/"),
                    PendingExport(revised, "/api/jobs/a/"),
                ],
            )
            remove_pending(path, first)
            self.assertEqual(
                pending_exports(path), [PendingExport(other, "/api/jobs/b/")]
            )

    def test_append_destination_is_saved_and_legacy_jobs_default_to_new(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.json"
            export = PendingExport(
                ImportPlan(
                    [{"id": 1}], {}, "background", "flows", "foreground", append=True
                ),
                "/api/jobs/a/",
            )
            save_pending(path, export)
            self.assertEqual(pending_exports(path), [export])
            payload = json.loads(path.read_text())
            del payload[0]["plan"]["append"]
            path.write_text(json.dumps(payload))
            self.assertFalse(pending_exports(path)[0].plan.append)

    def test_replacement_mode_round_trips_for_pending_exports(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "jobs.json"
            item = PendingExport(
                ImportPlan(
                    [{"id": 1}],
                    {},
                    "background",
                    "flows",
                    "foreground",
                    append=True,
                    replace=True,
                ),
                "/api/jobs/a/",
            )
            save_pending(path, item)
            self.assertEqual(pending_exports(path), [item])
