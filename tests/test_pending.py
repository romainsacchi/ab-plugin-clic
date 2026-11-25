from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

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
